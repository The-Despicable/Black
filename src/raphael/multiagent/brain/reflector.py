"""Loop 1 — the Reflector: distills insights and revises confidence."""
from __future__ import annotations

from typing import List, Optional

from raphael.multiagent.brain import memory as mem
from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.config import Config
from raphael.multiagent.llm.base import ChatMessage
from raphael.multiagent.llm.registry import Registry
from raphael.multiagent.ui import info, ok


def reflect_session(
    cfg: Config,
    db: BrainDB,
    registry: Registry,
    session_id: str,
    kind: str,
    topic: str,
    turns: List[dict],
    quiet: bool = False,
) -> None:
    if not turns:
        return
    rb = registry.binding("reflector")
    rprovider = registry.provider(rb.provider)

    transcript = "\n\n".join(f"[{t['agent']}]: {t['text']}" for t in turns)[:6000]
    outcomes_rows = db.query(
        "SELECT subject, score FROM outcomes WHERE session_id=? ORDER BY score DESC", (session_id,)
    )
    outcome_line = ", ".join(f"{r['subject']}={r['score']}" for r in outcomes_rows) or "none"

    # candidate past insights to confirm/contradict
    past = mem.recall(db, f"{kind}: {topic}", top_k=5)
    past_block = "\n".join(f"- [{iid}] {text} (confidence {conf:.2f})" for iid, text, conf, _ in past) or "(none)"

    messages = [
        ChatMessage(role="system", content=(
            f"[topic:{topic}]\n" + _persona(db, "reflector")
        )),
        ChatMessage(role="user", content=(
            f"Session kind: {kind}. Topic: '{topic}'. Outcome scores: {outcome_line}.\n\n"
            f"TRANSCRIPT (truncated):\n{transcript}\n\n"
            f"PAST INSIGHTS to validate against this session:\n{past_block}\n\n"
            "Reply ONLY with the JSON code block: new general insights + "
            "confirmations/contradictions of past insight ids."
        )),
    ]
    from raphael.multiagent.brain.evolver import ask_json_raw  # small shared helper

    parsed = ask_json_raw(rprovider, rb.model, messages, max_tokens=800)
    if not parsed:
        info("reflector produced no parseable output this session")
        return

    added = 0
    for ins in parsed.get("insights") or []:
        text = str(ins.get("text", "")).strip()
        if len(text) < 12:
            continue
        conf = _clamp(ins.get("confidence", 0.6))
        mem.add_insight(db, session_id, text, conf)
        added += 1

    revised = 0
    for c in parsed.get("confirmations") or []:
        try:
            iid = int(c.get("insight_id"))
            rel = str(c.get("relation", "neutral")).lower()
        except (TypeError, ValueError):
            continue
        if rel == "confirmed":
            mem.adjust_confidence(db, iid, +0.08, confirmed=True)
            revised += 1
        elif rel == "contradicted":
            mem.adjust_confidence(db, iid, -0.10, confirmed=False)
            revised += 1

    max_active = int(cfg.memory.get("max_insights", 500))
    pruned = mem.prune(db, max_active)

    if not quiet:
        ok(f"brain: +{added} insights, {revised} confidences revised, {pruned} pruned")


def _clamp(v, lo=0.05, hi=0.95) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return 0.6


def _persona(db: BrainDB, role: str) -> str:
    from raphael.multiagent.personas import get_persona_prompt

    return get_persona_prompt(db, role)
