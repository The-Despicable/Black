"""Chat orchestrator — one user turn ⇄ one assistant reply, memory-aware.

A chat is a normal brain session (kind='chat'): user messages and assistant
replies are journaled as turns, so a window can hand ``--session <id>`` back
to continue where it left off, and ``brain sessions`` lists it like any other
session. Memory injection and the governance kill-switch apply exactly as
they do for debate / community / teams.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional, Tuple

from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.brain import memory as mem
from raphael.multiagent.config import Config, RoleBinding
from raphael.multiagent.llm.base import ChatMessage
from raphael.multiagent.llm.registry import Registry
from raphael.multiagent.log import get_logger
from raphael.multiagent.orchestrators.base import SessionRunner

log = get_logger("chat")

USER_AGENT = "user"        # agent column value for human messages
BOT_AGENT = "chat"         # agent column value for assistant replies
HISTORY_WINDOW = 16        # most recent turns sent to the provider


# ---------------------------------------------------------------- journal
def _next_seq(db: BrainDB, session_id: str) -> int:
    row = db.one(
        "SELECT COALESCE(MAX(seq),0)+1 AS n FROM turns WHERE session_id=?",
        (session_id,),
    )
    return int(row["n"]) if row else 1


def append_user_turn(db: BrainDB, session_id: str, seq: int, text: str) -> None:
    """Journal a human message (no provider involved, provider fields NULL)."""
    db.execute(
        "INSERT INTO turns(session_id, seq, agent, role, phase, round, provider, model,"
        " content, latency_ms, ok, created_at) VALUES(?,?,?,NULL,'chat',?,NULL,NULL,?,NULL,1,?)",
        (
            session_id, seq, USER_AGENT, seq, text[-4000:],
            _dt.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    db.commit()


def fetch_history(db: BrainDB, session_id: str) -> List[Tuple[str, str]]:
    """Full (agent, content) history in order — transcript + context."""
    rows = db.query(
        "SELECT agent, content FROM turns WHERE session_id=? AND ok=1 ORDER BY seq",
        (session_id,),
    )
    return [(str(r["agent"]), str(r["content"])) for r in rows]


def resolve_session(db: BrainDB, session: Optional[str]) -> Optional[Dict[str, str]]:
    if not session:
        return None
    row = db.one("SELECT id, topic FROM sessions WHERE id=?", (session,))
    if row is None:
        raise KeyError(f"chat session not found: {session}")
    return {"id": str(row["id"]), "topic": str(row["topic"] or "chat")}


# ----------------------------------------------------------------- runner
def run_chat(
    cfg: Config,
    db: BrainDB,
    registry: Registry,
    message: str,
    session: Optional[str] = None,
    quiet: bool = False,
    stream: bool = True,
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
) -> Dict[str, object]:
    """Send one user message and stream back one assistant reply.

    Pass ``session=<existing chat session id>`` to keep a multi-turn
    conversation; without it, a new session is opened per message.
    ``provider_override``/``model_override`` pin this single turn to a
    specific provider/model (both required together); without them the
    ``roles.chat`` binding (or the first enabled provider's live models)
    decides. Returns a dict describing the exchange (NDJSON-friendly).
    """
    if bool(provider_override) != bool(model_override):
        raise ValueError("--provider and --model must be given together")
    existing = resolve_session(db, session)
    topic = existing["topic"] if existing else ((message or "chat")[:80] or "chat")

    runner = SessionRunner(
        cfg, db, registry, "chat", topic,
        session_id=existing["id"] if existing else None,
        quiet=quiet, stream=stream,
    )
    runner.gate("chat_turn", seq="resume" if existing else "new", mode=cfg.mode)

    seq = _next_seq(db, runner.session_id)
    append_user_turn(db, runner.session_id, seq, message)
    # run_turn journals seq=self.turn_seq+1; resume must continue the shared
    # sequence so user/assistant turns interleave in insertion order (issue
    # hit as user→chat→chat→user otherwise).
    runner.turn_seq = seq - 1

    # -- memory injection ----------------------------------------------------
    wisdom, used_ids = runner.memory_system_block(f"chat: {message}")
    if used_ids:
        mem.mark_used(db, used_ids)

    system = runner.persona_system(
        "chat", extra_tags="[chat]" + (f"\n{wisdom}" if wisdom else "")
    )
    history = fetch_history(db, runner.session_id)
    messages: List[ChatMessage] = [ChatMessage(role="system", content=system)]
    for agent_name, content in history[-HISTORY_WINDOW:]:
        role = "user" if agent_name == USER_AGENT else "assistant"
        messages.append(ChatMessage(role=role, content=content))

    if provider_override and model_override:
        binding = RoleBinding(provider_override, model_override)
    else:
        binding = registry.binding("chat")
    provider = registry.provider(binding.provider)
    reply = runner.run_turn(
        agent=BOT_AGENT,
        role="chat",
        provider_name=binding.provider,
        provider=provider,
        model=binding.model,
        messages=messages,
        phase="chat",
        round_no=seq,
        temperature=0.6,
    )

    # -- transcript = the FULL session, not just this exchange ----------------
    runner.section(f"chat · {topic}")
    for agent_name, content in history:
        label = "you" if agent_name == USER_AGENT else "assistant"
        runner.add_to_section(label, "", content)

    runner.finish()

    return {
        "session_id": runner.session_id,
        "reply": reply,
        "provider": binding.provider,
        "model": binding.model,
        "mode": cfg.mode,
    }
