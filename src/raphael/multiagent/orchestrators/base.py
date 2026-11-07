"""Shared session machinery used by all orchestrators."""
from __future__ import annotations

import datetime as _dt
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.brain import memory as mem
from raphael.multiagent.config import Config
from raphael.multiagent.governance import Governance, KillSwitchEngaged, get_governance
from raphael.multiagent.llm.base import ChatMessage, Provider
from raphael.multiagent.llm.registry import Registry
from raphael.multiagent.log import get_logger
from raphael.multiagent.personas import get_persona_prompt
from raphael.multiagent.transcript import write_transcript
from raphael.multiagent.ui import agent_color, console, extract_json, info, is_json_mode, stream_turn
from rich.panel import Panel
from rich.text import Text


def emit_event(payload: dict) -> None:
    """Print one NDJSON progress event on stdout (``--json`` mode only).

    Run screens (debate / chat / community / teams) subscribe to these to
    render each agent turn live: one compact JSON object per line, flushed
    immediately so the TUI's stdout tap sees it while the command runs.
    Final results are separate top-level objects; everything that carries an
    ``event`` key is progress, not a result."""
    if not is_json_mode():
        return
    import json as _json

    print(_json.dumps({"event": "turn", **payload}, ensure_ascii=False, default=str), flush=True)

log = get_logger("session")


class SessionRunner:
    """Owns one session: turns, brain writes, transcripts, verdict storage."""

    def __init__(
        self,
        cfg: Config,
        db: BrainDB,
        registry: Registry,
        kind: str,
        topic: str,
        quiet: bool = False,
        stream: bool = True,
        governance: Optional[Governance] = None,
        session_id: Optional[str] = None,
    ):
        self.cfg = cfg
        self.db = db
        self.registry = registry
        self.kind = kind
        self.topic = topic
        self.quiet = quiet
        self.stream = stream
        self.gov: Governance = governance or get_governance(cfg)
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.started = _dt.datetime.now().isoformat(timespec="seconds")
        self.turn_seq = 0
        self.sections: List[dict] = []
        self.verdict: Optional[dict] = None
        self.transcript_file: Optional[Path] = None
        if session_id is None:
            # fresh session row; resumed sessions (session_id given) already have one
            self.db.execute(
                "INSERT INTO sessions(id, kind, topic, mode, started_at) VALUES(?,?,?,?,?)",
                (self.session_id, kind, topic, cfg.mode, self.started),
            )
        self.db.commit()
        self.gov.audit({
            "event": "session_start", "session_id": self.session_id,
            "kind": kind, "topic": topic, "mode": cfg.mode,
        })
        self._last_turn_latency_ms: int = 0

    # -------------------------------------------------------- governance
    def gate(self, action: str, **context: object) -> None:
        """Kill-switch gate; raises KillSwitchEngaged to abort the session."""
        self.gov.check(action, {"session_id": self.session_id, "kind": self.kind, **context})

    # ------------------------------------------------------------------ turns
    def persona_system(self, role: str, extra_tags: str = "") -> str:
        prompt = get_persona_prompt(self.db, role)
        if extra_tags:
            prompt = f"{prompt}\n{extra_tags}"
        return prompt

    def memory_system_block(self, query: str) -> Tuple[str, List[int]]:
        if not self.cfg.memory.get("injection", True):
            return "", []
        top_k = int(self.cfg.memory.get("top_k", 3))
        return mem.memory_block(self.db, f"{query}", top_k=top_k)

    def run_turn(
        self,
        agent: str,
        role: str,
        provider_name: str,
        provider: Provider,
        model: str,
        messages: List[ChatMessage],
        phase: str,
        round_no: int = 0,
        team: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        emit_event: bool = True,
    ) -> str:
        """Execute one agent turn: stream it, record it in the journal.

        Set ``emit_event=False`` when the caller post-processes the text
        (e.g. adding debate headings) and wants to emit the NDJSON event
        itself with the final text.
        """
        self.turn_seq += 1
        meta = f"{model} · {provider_name}"
        t0 = time.time()
        ok_flag = 1
        text = ""
        try:
            text = stream_turn(
                agent,
                meta,
                provider.stream_chat(
                    model, messages, temperature=temperature, max_tokens=max_tokens
                ),
                quiet=self.quiet,
                stream=self.stream,
            )
        except Exception as exc:  # provider failure recorded, session continues
            ok_flag = 0
            from raphael.multiagent.ui import error

            log.warning("turn failed (agent=%s model=%s): %s", agent, model, exc, exc_info=True)
            error(f"{agent}: {exc}")
            self.gov.audit({
                "event": "turn_failed", "session_id": self.session_id,
                "agent": agent, "model": model, "phase": phase,
                "error": str(exc)[:300],
            })
            text = "(turn failed)"
        latency = round((time.time() - t0) * 1000, 1)
        self._last_turn_latency_ms = latency
        if emit_event:
            from raphael.multiagent.orchestrators.base import emit_event as _emit_event
            _emit_event({
                "session_id": self.session_id,
                "agent": agent,
                "role": role,
                "team": team,
                "phase": phase,
                "round": round_no,
                "provider": provider_name,
                "model": model,
                "latency_ms": latency,
                "ok": bool(ok_flag),
                "text": text,
            })
        self.db.execute(
            "INSERT INTO turns(session_id, seq, agent, team, role, phase, round, provider, model,"
            " content, latency_ms, ok, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.session_id, self.turn_seq, agent, team, role, phase, round_no,
                provider_name, model, text, latency, ok_flag, _dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.db.commit()
        return text

    def ask_json(
        self,
        agent: str,
        role: str,
        provider: Provider,
        model: str,
        provider_name: str,
        messages: List[ChatMessage],
        phase: str,
        max_tokens: Optional[int] = 900,
        retries: int = 2,
    ) -> Optional[dict]:
        """Ask for a JSON reply with tolerant parsing and one repair retry."""
        for attempt in range(retries):
            self.turn_seq += 1
            t0 = time.time()
            try:
                text = "".join(
                    provider.stream_chat(model, messages, temperature=0.2, max_tokens=max_tokens)
                )
            except Exception as exc:
                from raphael.multiagent.ui import error

                log.warning("json turn failed (agent=%s model=%s): %s", agent, model, exc, exc_info=True)
                error(f"{agent}: {exc}")
                return None
            latency = round((time.time() - t0) * 1000, 1)
            self.db.execute(
                "INSERT INTO turns(session_id, seq, agent, role, phase, provider, model,"
                " content, latency_ms, ok, created_at) VALUES(?,?,?,?,?,?,?,?,?,1,?)",
                (self.session_id, self.turn_seq, agent, role, phase, provider_name, model, text, latency,
                 _dt.datetime.now().isoformat(timespec="seconds")),
            )
            self.db.commit()
            parsed = extract_json(text)
            if parsed is not None:
                return parsed
            messages = list(messages) + [
                ChatMessage(role="assistant", content=text),
                ChatMessage(
                    role="user",
                    content="That reply was not a single valid JSON object. Reply again with ONLY the JSON code block, no prose.",
                ),
            ]
        return None

    # ------------------------------------------------------------------ verdict
    def record_outcome(
        self, subject: str, subject_type: str, score: float, detail: Optional[dict] = None
    ) -> None:
        import json as _json

        self.db.execute(
            "INSERT INTO outcomes(session_id, subject, subject_type, score, detail_json, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (self.session_id, subject, subject_type, score,
             _json.dumps(detail or {}), _dt.datetime.now().isoformat(timespec="seconds")),
        )
        self.db.commit()

    def finish(
        self,
        verdict: Optional[dict] = None,
        extra_footer: Optional[Dict[str, str]] = None,
    ) -> str:
        import json as _json

        self.verdict = verdict
        finished = _dt.datetime.now().isoformat(timespec="seconds")
        tdir = Path(str((self.cfg.raw.get("transcripts") or {}).get("dir", "./transcripts")))
        tpath = transcript_file = None
        from raphael.multiagent.transcript import transcript_path

        tpath = transcript_path(tdir, self.kind, self.topic)
        footer = dict(extra_footer or {})
        if verdict:
            footer["verdict"] = _json.dumps(verdict, ensure_ascii=False)[:600]
        write_transcript(tpath, self.kind, self.topic, self.sections, footer or None)
        self.db.execute(
            "UPDATE sessions SET finished_at=?, verdict_json=?, transcript_path=? WHERE id=?",
            (finished, _json.dumps(verdict, ensure_ascii=False) if verdict else None, str(tpath), self.session_id),
        )
        self.db.commit()
        self.transcript_file = tpath
        self.gov.audit({
            "event": "session_end", "session_id": self.session_id, "kind": self.kind,
            "topic": self.topic,
            "verdict": (verdict or {}).get("winner") or (verdict or {}).get("synthesis") or None,
            "turns": self.turn_seq, "transcript": str(tpath),
        })
        if not self.quiet:
            from raphael.multiagent.ui import ok as _ok

            _ok(f"transcript → {tpath}")
        return str(tpath)

    def section(self, heading: str) -> None:
        from raphael.multiagent.ui import phase_header

        phase_header(heading)
        self.sections.append({"heading": heading, "turns": []})

    def add_to_section(self, agent: str, meta: str, text: str) -> None:
        if self.sections:
            self.sections[-1].setdefault("turns", []).append(
                {"agent": agent, "meta": meta, "text": text}
            )

    def close(self) -> None:
        self.db.commit()

    def abort(self, reason: str) -> None:
        """Mark the session aborted (kill switch / fatal path) and audit it."""
        import json as _json

        finished = _dt.datetime.now().isoformat(timespec="seconds")
        self.db.execute(
            "UPDATE sessions SET finished_at=?, metrics_json=? WHERE id=?",
            (finished, _json.dumps({"aborted": True, "reason": reason[:300]}), self.session_id),
        )
        self.db.commit()
        self.gov.audit({
            "event": "session_aborted", "session_id": self.session_id,
            "kind": self.kind, "reason": reason[:300],
        })
