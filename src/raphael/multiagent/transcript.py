"""Markdown transcript export."""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import List, Optional


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:max_len].rstrip("-")) or "session"


def transcript_path(base_dir: Path, kind: str, topic: str) -> Path:
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return base_dir / f"{ts}-{kind}-{slugify(topic)}.md"


def write_transcript(
    path: Path,
    kind: str,
    topic: str,
    sections: List[dict],
    footer: Optional[dict] = None,
) -> Path:
    """sections: [{heading, turns: [{agent, meta, text}], raw}]"""
    lines = [f"# RAPHAEL-MA · {kind.upper()} · {topic}", ""]
    lines.append(f"*{ _dt.datetime.now().isoformat(timespec='seconds') }*")
    lines.append("")
    for sec in sections:
        lines.append(f"## {sec.get('heading', '')}")
        lines.append("")
        for t in sec.get("turns", []):
            lines.append(f"**[{t['agent']}]** · {t.get('meta', '')}")
            lines.append("")
            lines.append(t["text"].strip())
            lines.append("")
        if sec.get("raw"):
            lines.append(str(sec["raw"]))
            lines.append("")
    if footer:
        lines.append("## Session record")
        lines.append("")
        for k, v in footer.items():
            lines.append(f"- **{k}:** {v}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
