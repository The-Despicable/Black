"""Loop 2 — the Evolver: rewrites the system's own genome under selection pressure.

Pipeline:
  1. collect performance stats (judge scores per persona, provider latency,
     insight dynamics) since the last accepted evolution
  2. ask the evolver model for surgical genome edits (whitelisted)
  3. store + apply the edits as a new genome version (status=active)
  4. after `eval_after` further sessions, compare metrics; keep or revert
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Dict, List, Optional

from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.config import Config
from raphael.multiagent.llm.base import ChatMessage, Provider
from raphael.multiagent.llm.registry import Registry
from raphael.multiagent.log import get_logger
from raphael.multiagent.personas import append_directive, replace_prompt
from raphael.multiagent.ui import error, info, ok, summary_table

log = get_logger("evolver")

STRATEGY_WHITELIST = {
    "debate.rounds", "community.rounds", "community.agents",
    "teams.internal_rounds", "memory.top_k", "memory.injection",
    "evolve.eval_sessions",
}


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def ask_json_raw(
    provider: Provider, model: str, messages: List[ChatMessage], max_tokens: int = 900, retries: int = 2
) -> Optional[dict]:
    from raphael.multiagent.ui import extract_json

    for _ in range(retries):
        try:
            text = "".join(provider.stream_chat(model, messages, temperature=0.2, max_tokens=max_tokens))
        except Exception as exc:
            log.warning("evolver provider call failed: %s", exc, exc_info=True)
            error(f"provider call failed: {exc}")
            return None
        parsed = extract_json(text)
        if parsed is not None:
            return parsed
        messages = list(messages) + [
            ChatMessage(role="assistant", content=text),
            ChatMessage(role="user", content="Not valid JSON. Reply again with ONLY the JSON code block."),
        ]
    return None


# --------------------------------------------------------------------- stats
def collect_stats(db: BrainDB) -> dict:
    persona_scores: Dict[str, List[float]] = {}
    for row in db.query(
        "SELECT t.role AS role, o.score AS score FROM outcomes o "
        "JOIN turns t ON t.session_id = o.session_id AND t.agent = o.subject "
        "WHERE o.subject_type='agent' GROUP BY o.id"
    ):
        if row["role"]:
            persona_scores.setdefault(row["role"], []).append(float(row["score"] or 0))

    persona_stats = {
        role: {
            "mean_score": round(sum(v) / len(v), 2),
            "n_scores": len(v),
        }
        for role, v in persona_scores.items()
    }

    provider_stats = {}
    for row in db.query(
        "SELECT provider, COUNT(*) AS n, AVG(latency_ms) AS lat, SUM(1-ok) AS fails FROM turns GROUP BY provider"
    ):
        if row["provider"]:
            provider_stats[row["provider"]] = {
                "turns": int(row["n"] or 0),
                "avg_latency_ms": round(float(row["lat"] or 0), 0),
                "failed": int(row["fails"] or 0),
            }

    insight_rows = db.query(
        "SELECT COUNT(*) AS n, AVG(confidence) AS conf, SUM(times_confirmed) AS c, "
        "SUM(times_contradicted) AS x, SUM(active) AS a FROM insights"
    )
    ir = insight_rows[0] if insight_rows else None
    insight_stats = {
        "total": int(ir["n"] or 0) if ir else 0,
        "avg_confidence": round(float(ir["conf"] or 0), 2) if ir else 0,
        "confirmed": int(ir["c"] or 0) if ir else 0,
        "contradicted": int(ir["x"] or 0) if ir else 0,
        "active": int(ir["a"] or 0) if ir else 0,
    }
    sessions = db.one("SELECT COUNT(*) AS n FROM sessions")["n"]
    return {
        "sessions_total": int(sessions or 0),
        "persona_scores": persona_stats,
        "providers": provider_stats,
        "insights": insight_stats,
    }


def _genome_snapshot(db: BrainDB) -> dict:
    personas = {
        row["role"]: {"version": int(row["version"]), "prompt_sha": _sha(row["prompt"][:200])}
        for row in db.query("SELECT role, version, prompt FROM personas WHERE active=1")
    }
    strat = {k: db.get_meta(k) for k in STRATEGY_WHITELIST}
    return {"personas": personas, "strategy": strat}


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------- evolving
def run_evolver(
    cfg: Config,
    db: BrainDB,
    registry: Registry,
    dry_run: bool = False,
    quiet: bool = False,
) -> Optional[dict]:
    if not (cfg.evolve_cfg.get("enabled", True)):
        info("evolution disabled in config")
        return None
    min_sessions = int(cfg.evolve_cfg.get("min_sessions", 3))
    stats = collect_stats(db)
    if stats["sessions_total"] < min_sessions:
        info(f"only {stats['sessions_total']} session(s); evolution wants >= {min_sessions} — skipping")
        return None

    eb = registry.binding("evolver")
    eprovider = registry.provider(eb.provider)

    persona_prompts = {
        row["role"]: row["prompt"][:400]
        for row in db.query("SELECT role, prompt FROM personas WHERE active=1")
    }
    messages = [
        ChatMessage(role="system", content=_persona(db, "evolver")),
        ChatMessage(role="user", content=(
            "CURRENT GENOME (truncated prompts):\n"
            + json.dumps(persona_prompts, indent=1)
            + "\n\nPERFORMANCE STATS:\n"
            + json.dumps(stats, indent=1)
            + "\n\nSTRATEGY KEYS you may set: "
            + ", ".join(sorted(STRATEGY_WHITELIST))
            + "\n\nPropose at most 4 edits. Reply ONLY with the JSON code block."
        )),
    ]
    proposal = ask_json_raw(eprovider, eb.model, messages, max_tokens=1200)
    if not proposal:
        error("evolver produced no parseable proposal")
        return None
    edits = [e for e in (proposal.get("edits") or []) if isinstance(e, dict)]
    edits = _validate_edits(db, edits)

    if not edits:
        info("evolver proposed no valid edits this round")
        return None

    if dry_run:
        if not quiet:
            summary_table(
                "Proposed genome edits (dry run)",
                [
                    {"target": e["target"], "field": e.get("field"), "action": e.get("action"),
                     "value": str(e.get("value"))[:60], "reason": str(e.get("reason", ""))[:60]}
                    for e in edits
                ],
            )
        return {"edits": edits, "dry_run": True}

    metrics_before = {
        "stats": stats,
        "genome": _genome_snapshot(db),
    }
    eval_after = int(cfg.evolve_cfg.get("eval_sessions", 5))
    try:
        db.execute(
            "INSERT INTO evolutions(kind, edits_json, reason, status, metrics_before_json,"
            " eval_after, sessions_seen, created_at) VALUES('genome',?,?,?,?,?,0,?)",
            (
                json.dumps(edits, ensure_ascii=False),
                "; ".join(str(e.get("reason", ""))[:80] for e in edits),
                "active",
                json.dumps(metrics_before, ensure_ascii=False),
                eval_after,
                _now(),
            ),
        )
        applied = _apply_edits(db, cfg, edits)
        db.commit()
    except Exception:
        log.warning("evolution transaction failed; rolling back", exc_info=True)
        db.rollback()
        raise
    if not quiet:
        ok(f"evolution applied: {applied} edit(s); evaluation after {eval_after} more session(s)")
        summary_table(
            "Genome edits applied",
            [
                {"target": e["target"], "action": e.get("action"), "value": str(e.get("value"))[:60]}
                for e in edits
            ],
        )
    return {"edits": edits, "applied": applied}


def _persona(db: BrainDB, role: str) -> str:
    from raphael.multiagent.personas import get_persona_prompt

    return get_persona_prompt(db, role)


def _validate_edits(db: BrainDB, edits: List[dict]) -> List[dict]:
    valid = []
    roles = {r["role"] for r in db.query("SELECT role FROM personas WHERE active=1")}
    for e in edits:
        target = str(e.get("target", ""))
        field = str(e.get("field", ""))
        action = str(e.get("action", "append"))
        value = e.get("value")
        if target.startswith("persona:"):
            role = target.split(":", 1)[1]
            if role in roles and field == "prompt" and value and action in ("append", "replace"):
                if action == "append" and len(str(value)) > 400:
                    value = str(value)[:400]
                e = dict(e, value=value)
                valid.append(e)
        elif target == "strategy":
            if field in STRATEGY_WHITELIST and value is not None:
                try:
                    if "." in field:
                        cast = int if field.split(".", 1)[1] in ("rounds", "agents", "top_k", "internal_rounds", "eval_sessions") else bool
                    else:
                        cast = int
                    e = dict(e, value=cast(value))
                    valid.append(e)
                except (TypeError, ValueError):
                    continue
        # routing edits are read-only for now (config file owns routing)
    return valid


def _apply_edits(db: BrainDB, cfg: Config, edits: List[dict]) -> int:
    applied = 0
    for e in edits:
        target = str(e["target"])
        if target.startswith("persona:"):
            role = target.split(":", 1)[1]
            if e.get("action") == "replace":
                replace_prompt(db, role, str(e["value"]), note=str(e.get("reason", ""))[:100])
            else:
                append_directive(db, role, str(e["value"]), note=str(e.get("reason", ""))[:100])
            applied += 1
        elif target == "strategy":
            db.set_meta(e["field"], e["value"])
            applied += 1
    return applied


# ------------------------------------------------------------------ selection
def tick_evolution_counters(db: BrainDB) -> None:
    """Called after every session: count it toward pending evaluations."""
    db.execute("UPDATE evolutions SET sessions_seen = sessions_seen + 1 WHERE status='active'")
    db.commit()


def evaluate_pending(cfg: Config, db: BrainDB, quiet: bool = False) -> List[dict]:
    """Selection gate: keep evolutions that improved, revert those that didn't."""
    decided = []
    for row in db.query("SELECT * FROM evolutions WHERE status='active' AND sessions_seen >= eval_after"):
        eid = int(row["id"])
        before = json.loads(row["metrics_before_json"] or "{}")
        stats_before = (before.get("stats") or {}).get("persona_scores") or {}
        stats_now = collect_stats(db)["persona_scores"]
        genome_before = (before.get("genome") or {}).get("personas") or {}
        genome_now = _genome_snapshot(db)["personas"]

        improved = _compare(stats_before, stats_now)
        if improved is None:
            # no comparable scores; judge by genome drift only -> keep conservatively
            improved = False
        status = "kept" if improved else "reverted"
        if improved:
            db.execute(
                "UPDATE evolutions SET status='kept', metrics_after_json=?, decided_at=? WHERE id=?",
                (json.dumps(collect_stats(db)), _now(), eid),
            )
        else:
            _revert(db, json.loads(row["edits_json"] or "[]"), genome_before)
            db.execute(
                "UPDATE evolutions SET status='reverted', metrics_after_json=?, decided_at=? WHERE id=?",
                (json.dumps(collect_stats(db)), _now(), eid),
            )
        decided.append({"id": eid, "status": status})
        if not quiet:
            from raphael.multiagent.ui import warn as _warn

            if status == "reverted":
                _warn(f"evolution #{eid} reverted: performance did not improve")
            else:
                ok(f"evolution #{eid} kept: performance improved")
    return decided


def _compare(before: dict, now: dict) -> Optional[bool]:
    """True if mean persona scores improved on comparable roles."""
    deltas = []
    for role, stats in now.items():
        b = before.get(role)
        if b and b.get("n_scores") and stats.get("n_scores"):
            deltas.append(stats["mean_score"] - b["mean_score"])
    if not deltas:
        return None
    avg = sum(deltas) / len(deltas)
    return avg > 0.05  # needs a real margin, not noise


def _revert(db: BrainDB, edits: List[dict], genome_before: dict) -> None:
    for e in edits:
        target = str(e.get("target", ""))
        if target.startswith("persona:"):
            role = target.split(":", 1)[1]
            row = db.one(
                "SELECT prompt, version FROM personas WHERE role=? ORDER BY version DESC LIMIT 1", (role,)
            )
            if row:
                import datetime as _dt

                db.execute("UPDATE personas SET active=0 WHERE role=?", (role,))
                # restore previous active version (the one before the edit)
                prev = db.one(
                    "SELECT version FROM personas WHERE role=? AND version < ? ORDER BY version DESC LIMIT 1",
                    (role, row["version"]),
                )
                if prev:
                    db.execute(
                        "UPDATE personas SET active=1 WHERE role=? AND version=?", (role, prev["version"])
                    )
        elif target == "strategy":
            key = e.get("field")
            old = genome_before.get("strategy", {}).get(key) if genome_before else None
            if old is not None:
                db.set_meta(key, old)
            else:
                db.set_meta(key, "0")
                db.execute("DELETE FROM meta WHERE key=?", (key,))
    db.commit()


def rollback_evolution(db: BrainDB, evolution_id: int) -> bool:
    row = db.one("SELECT * FROM evolutions WHERE id=?", (evolution_id,))
    if not row:
        return False
    if row["status"] in ("reverted",):
        return True  # already reverted
    genome_before = (json.loads(row["metrics_before_json"] or "{}").get("genome") or {})
    _revert(db, json.loads(row["edits_json"] or "[]"), genome_before)
    db.execute(
        "UPDATE evolutions SET status='reverted', decided_at=? WHERE id=?", (_now(), evolution_id)
    )
    db.commit()
    return True
