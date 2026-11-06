"""Shared widgets and render helpers for the raphael-ma TUI."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from textual.containers import Horizontal
from textual.widgets import DataTable, RichLog, Static

from raphael.multiagent.tui.engine import RunResult

# ---------------------------------------------------------------------------
# small chrome widgets


class Badge(Static):
    """One-line status chip colored by tone (mock / live / danger ...)."""

    def __init__(self, label: str = "", tone: str = "dim", **kwargs: Any) -> None:
        super().__init__(label, **kwargs)
        self.set_classes(f"badge {tone}")

    def set_badge(self, label: str, tone: str) -> None:
        self.update(label)
        self.set_classes(f"badge {tone}")


class StatusStrip(Horizontal):
    """Always-visible state line: mode badge · governance · home · busy."""

    def on_mount(self) -> None:
        self.set_interval(0.5, self._refresh)

    def _refresh(self) -> None:
        try:
            app = self.app
            state = app.state  # type: ignore[attr-defined]
        except Exception:
            return
        mode = self.query_one("#strip-mode", Badge)
        if state.armed_live:
            mode.set_badge("LIVE · ARMED", "live")
        else:
            mode.set_badge("MOCK", "mock")
        gov = "gov:" + state.governance_type
        gov += " · kill-switch:" + ("on" if state.kill_switch_set else "—")
        gov += " · strict:" + ("on" if state.strict else "off")
        if state.unrestricted:
            gov = "gov:UNRESTRICTED · kill-switch:— · strict:off"
        self.query_one("#strip-gov", Static).update(gov)
        home = str(state.home)
        if len(home) > 34:
            home = "…" + home[-33:]
        self.query_one("#strip-home", Static).update(home)
        busy = self.query_one("#strip-busy", Static)
        busy.update("● running" if state.busy else "")

    def compose(self) -> None:
        yield Badge("MOCK", "mock", id="strip-mode")
        yield Static("gov:—", id="strip-gov", classes="strip-item")
        yield Static("", id="strip-home", classes="strip-item")
        yield Static("", id="strip-busy", classes="strip-item")


class CommandBar(Static):
    """Shows the exact argv the screen will hand to raphael-ma."""

    def set_argv(self, argv: Sequence[str]) -> None:
        joined = " ".join(shlex.quote(str(a)) for a in argv)
        self.update(f"❯ raphael-ma {joined}")


class ResultBanner(Static):
    """Exit code / outcome / duration of the last command — never hidden."""

    def set_running(self, argv: Sequence[str], label: str = "") -> None:
        self.set_classes("result run")
        joined = " ".join(shlex.quote(str(a)) for a in argv)
        prefix = f"{label} — " if label else ""
        self.update(f"▶ {prefix}running raphael-ma {joined} …")

    def set_result(self, res: RunResult) -> None:
        tone = "ok" if res.ok else "fail"
        self.set_classes(f"result {tone}")
        note = ""
        if not res.ok and res.err:
            first_err = next((ln for ln in res.err_lines if ln.strip()), "")
            if first_err:
                note = f"  stderr: {first_err[:110]}"
        self.update(f"■ {res.label} · {res.duration:.2f}s{note}")


class OutputPane(RichLog):
    """Streams captured CLI stdout line-by-line while a command runs."""

    def __init__(self, id: str = "output", **kwargs: Any) -> None:
        super().__init__(id=id, highlight=True, markup=False, wrap=True, max_lines=4000, **kwargs)
        self._engine: Any = None
        self._timer: Any = None
        self._streamed = 0

    def bind_engine(self, engine: Any) -> None:
        self._engine = engine
        self._streamed = 0
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_interval(0.12, self._poll)

    def reset_stream(self) -> None:
        self.clear()
        self._streamed = 0
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _poll(self) -> None:
        if self._engine is None:
            return
        lines = self._engine.poll_out_lines()
        if lines:
            self.write_lines(lines)
            self._streamed += len(lines)

    def finalize(self, res: RunResult) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        tail = res.out_lines[self._streamed :]
        if tail:
            self.write_lines(tail)
        self._engine = None

    def write_lines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)


# ---------------------------------------------------------------------------
# NDJSON / table helpers (schema-agnostic: the real CLI output is the truth)


def parse_ndjson(text: str) -> List[Dict[str, Any]]:
    """Parse NDJSON rows emitted by ``--json`` mode (stdout)."""
    rows: List[Dict[str, Any]] = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def latest_models_row(res: Any) -> Optional[Dict[str, Any]]:
    """Latest ``{"provider", "models": [...]}`` row from ``providers models --json``."""
    rows = [r for r in parse_ndjson(getattr(res, "out", "") or "") if "models" in r]
    return rows[-1] if rows else None


def _fmt_cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "✓" if value else "✗"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (dict, list)):
        s = json.dumps(value)
        return s if len(s) <= 42 else s[:39] + "…"
    return str(value)


def populate_table(table: DataTable, rows: Sequence[Dict[str, Any]]) -> None:
    """Fill a DataTable from parsed NDJSON rows; columns = union of keys."""
    table.clear(columns=True)
    if not rows:
        return
    cols: List[str] = []
    for row in rows:
        for key in row:
            if key not in cols:
                cols.append(key)
    table.add_columns(*cols)
    for row in rows:
        table.add_row(*[_fmt_cell(row.get(c)) for c in cols])


_NUMERIC_HINTS = ("score", "mean", "avg", "average", "rating", "p50", "p95", "ms", "latency", "tokens")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def ascii_bars(rows: Sequence[Dict[str, Any]], width: int = 26) -> str:
    """Horizontal ASCII bars over the first numeric NDJSON column found."""
    if not rows:
        return ""
    numeric_key: Optional[str] = None
    for hint in _NUMERIC_HINTS:
        for row in rows:
            for key, value in row.items():
                if hint in str(key).lower() and _is_number(value):
                    numeric_key = key
                    break
            if numeric_key:
                break
        if numeric_key:
            break
    if numeric_key is None:
        for row in rows:
            for key, value in row.items():
                if _is_number(value):
                    numeric_key = key
                    break
            if numeric_key:
                break
    if numeric_key is None:
        return ""
    label_keys = [k for k in ("provider", "model", "persona", "name", "id") if k in rows[0]]
    label_key = label_keys[0] if label_keys else next(iter(rows[0]))
    values = [float(r.get(numeric_key, 0) or 0) for r in rows]
    vmax = max(abs(v) for v in values) or 1.0
    lines: List[str] = [f"{numeric_key}"]
    for row, value in zip(rows, values):
        label = _fmt_cell(row.get(label_key))[:24].ljust(24)
        bar = "▇" * max(1, round(abs(value) / vmax * width))
        lines.append(f"{label} {bar} {value:.4g}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# file helpers (documented data locations)


def tail_file(path: Path, last: int = 25) -> List[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    except Exception:
        return []
    lines = [ln for ln in lines if ln.strip()]
    return lines[-last:]


def resolve_first(*candidates: Path) -> Optional[Path]:
    for path in candidates:
        try:
            if path.exists():
                return path
        except Exception:
            continue
    return None
