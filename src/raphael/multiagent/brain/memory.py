"""Memory: insight storage, semantic recall, confirmation/contradiction."""
from __future__ import annotations

import datetime as _dt
from typing import Iterable, List, Optional, Tuple

from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.brain.vectors import cosine, embed, from_blob, to_blob


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def add_insight(
    db: BrainDB,
    session_id: str,
    text: str,
    confidence: float = 0.6,
) -> int:
    # dedup: identical text bumps confidence instead of duplicating
    row = db.one("SELECT id FROM insights WHERE text=?", (text,))
    if row:
        iid = int(row["id"])
        adjust_confidence(db, iid, +0.03, confirmed=True)
        return iid
    vec = embed(text)
    db.execute(
        "INSERT INTO insights(session_id, text, confidence, weight, embedding, active,"
        " created_at, updated_at) VALUES(?,?,?,?,?,1,?,?)",
        (session_id, text, confidence, 0.5, to_blob(vec), _now(), _now()),
    )
    db.commit()
    row = db.one("SELECT last_insert_rowid() AS id")
    return int(row["id"])


def recall(
    db: BrainDB,
    query: str,
    top_k: int = 3,
    include_inactive: bool = False,
) -> List[Tuple[int, str, float, float]]:
    """Return [(id, text, confidence, similarity)] ranked by relevance."""
    where = "" if include_inactive else "WHERE active=1"
    rows = db.query(f"SELECT id, text, confidence, embedding FROM insights {where}")
    qvec = embed(query)
    scored = []
    for r in rows:
        blob = r["embedding"]
        sim = cosine(qvec, from_blob(bytes(blob))) if blob else 0.0
        # relevance = similarity * confidence — wisdom must be both apt and trusted
        scored.append((int(r["id"]), r["text"], float(r["confidence"]), sim))
    scored.sort(key=lambda t: t[3] * t[2], reverse=True)
    return scored[:top_k]


def mark_used(db: BrainDB, insight_ids: Iterable[int]) -> None:
    ids = list(insight_ids)
    if not ids:
        return
    marks = ",".join("?" * len(ids))
    db.execute(f"UPDATE insights SET times_used = times_used + 1 WHERE id IN ({marks})", ids)
    db.commit()


def adjust_confidence(
    db: BrainDB, insight_id: int, delta: float, confirmed: bool
) -> float:
    col = "times_confirmed" if confirmed else "times_contradicted"
    row = db.one("SELECT confidence FROM insights WHERE id=?", (insight_id,))
    if not row:
        return 0.0
    new_conf = max(0.0, min(1.0, float(row["confidence"]) + delta))
    active = 1 if new_conf >= 0.25 else 0
    db.execute(
        f"UPDATE insights SET confidence=?, {col}={col}+1, active=?, updated_at=? WHERE id=?",
        (new_conf, active, _now(), insight_id),
    )
    db.commit()
    return new_conf


def active_insights(db: BrainDB) -> List[Tuple[int, str, float]]:
    rows = db.query("SELECT id, text, confidence FROM insights WHERE active=1 ORDER BY confidence DESC")
    return [(int(r["id"]), r["text"], float(r["confidence"])) for r in rows]


def prune(db: BrainDB, max_active: int) -> int:
    """Deactivate lowest-confidence insights beyond the cap."""
    rows = db.query(
        "SELECT id FROM insights WHERE active=1 ORDER BY confidence*weight DESC, times_used DESC"
    )
    excess = [int(r["id"]) for r in rows[max_active:]]
    for iid in excess:
        db.execute("UPDATE insights SET active=0, updated_at=? WHERE id=?", (_now(), iid))
    db.commit()
    return len(excess)


def memory_block(db: BrainDB, query: str, top_k: int = 3) -> Tuple[str, List[int]]:
    """Build the injectable 'accumulated wisdom' prompt block."""
    hits = recall(db, query, top_k=top_k)
    if not hits:
        return "", []
    lines = ["ACCUMULATED WISDOM FROM PAST SESSIONS (relevance-weighted, judge-validated):"]
    for iid, text, conf, sim in hits:
        lines.append(f"- {text} [confidence: {conf:.2f}]")
    lines.append("Use these where genuinely applicable; do not parrot them.")
    return "\n".join(lines), [iid for iid, _, _, _ in hits]
