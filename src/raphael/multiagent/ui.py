"""Rich console UI helpers: agent colors, streaming turns, tables, spinners."""
from __future__ import annotations

import json
import re
from typing import Dict, Iterator, List, Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from raphael.multiagent.log import get_logger

log = get_logger("ui")

console = Console()
_stderr_console = Console(stderr=True)

# Machine-readable output mode (raphael-ma --json): tables print as one JSON
# array per table (NDJSON, one line each) on stdout; status messages move
# to stderr; streaming panels are suppressed so stdout stays parseable.
_JSON_MODE = False


def set_json_mode(enabled: bool) -> None:
    global _JSON_MODE
    _JSON_MODE = bool(enabled)


def is_json_mode() -> bool:
    return _JSON_MODE


def _status_console() -> Console:
    return _stderr_console if _JSON_MODE else console

PALETTE = [
    "cyan", "magenta", "green", "yellow", "blue", "red",
    "bright_cyan", "bright_magenta", "bright_green", "bright_yellow",
    "bright_blue", "bright_red", "bright_white", "white",
]


def agent_color(name: str) -> str:
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return PALETTE[h % len(PALETTE)]


def banner(title: str, subtitle: str = "") -> None:
    text = Text()
    text.append("RAPHAEL-MA", style="bold white on blue")
    text.append(f"  {title}", style="bold")
    if subtitle:
        text.append(f"\n{subtitle}", style="dim")
    _status_console().print(Panel(text, border_style="blue"))


def phase_header(label: str) -> None:
    _status_console().rule(f"[bold blue]{label}", style="blue")


def stream_turn(
    agent: str,
    meta: str,
    deltas: Iterator[str],
    quiet: bool = False,
    stream: bool = True,
) -> str:
    """Stream an agent turn; return the assembled text."""
    color = agent_color(agent)
    if quiet or _JSON_MODE:
        chunks: List[str] = []
        for d in deltas:
            chunks.append(d)
        return "".join(chunks)
    title = f"[bold {color}]{agent}[/bold {color}] [dim]· {meta}[/dim]"
    if not stream:
        text = "".join(list(deltas))
        console.print(Panel(Text(text.rstrip()), title=title, border_style=color))
        return text
    body = Text()
    with Live(Panel(body, title=title, border_style=color), console=console, refresh_per_second=12):
        for d in deltas:
            body.append(d)
    console.print()
    return body.plain


def spinner_phase(label: str):
    return console.status(f"[bold blue]{label}", spinner="dots")


def summary_table(title: str, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    if _JSON_MODE:
        # one compact JSON line per table (NDJSON); title goes to stderr.
        # plain print(): Rich soft-wraps piped output at width 80, which
        # would break one-line-per-record parsing.
        _stderr_console.print(f"# {title}")
        print(json.dumps(rows, ensure_ascii=False, default=str))
        return
    table = Table(title=title, show_lines=False, header_style="bold")
    cols = list(rows[0].keys())
    for c in cols:
        table.add_column(str(c))
    for r in rows:
        table.add_row(*[str(r[c]) for c in cols])
    console.print(table)


def info(msg: str) -> None:
    _status_console().print(f"[dim]{msg}[/dim]")


def warn(msg: str) -> None:
    _status_console().print(f"[yellow]⚠ {msg}[/yellow]")


def ok(msg: str) -> None:
    _status_console().print(f"[green]✓ {msg}[/green]")


def error(msg: str) -> None:
    _status_console().print(f"[bold red]✗ {msg}[/bold red]")


JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extract_json(text: str) -> Optional[dict]:
    """Tolerantly pull the first JSON object out of an LLM reply."""
    m = JSON_BLOCK.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            log.debug("fenced JSON block unparseable: %s", exc)
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError as exc:
                        log.debug("brace-matched JSON unparseable: %s", exc)
                        return None
    return None
