"""Shared widgets and render helpers for the raphael-ma TUI."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shlex
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rich.text import Text
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

    _SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

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
        summary = getattr(state, "brain_summary", None)
        show_brain = bool(summary and getattr(app.screen, "SHOWS_BRAIN_STRIP", False))
        brain = self.query_one("#strip-brain", Static)
        # the home path yields its slot to the brain digest on run screens
        # (it lives in full on the dashboard HOME panel) so the clock never
        # gets pushed off the right edge
        self.query_one("#strip-home", Static).display = not show_brain
        brain.update(f"brain · {summary}" if show_brain else "")
        engine = self.query_one("#strip-engine", Badge)
        if state.engine_ok is None:
            engine.set_badge("engine …", "dim")
        elif state.engine_ok:
            engine.set_badge("engine ✓", "ok")
        else:
            engine.set_badge("engine ✗", "danger")
        busy = self.query_one("#strip-busy", Static)
        if state.busy:
            frame = self._SPIN[int(time.monotonic() * 10) % len(self._SPIN)]
            busy.update(f"{frame} running")
        else:
            busy.update("")
        clock = self.query_one("#strip-clock", Static)
        clock.update(time.strftime("%H:%M:%S"))

    def compose(self) -> None:
        yield Badge("MOCK", "mock", id="strip-mode")
        yield Static("", id="strip-busy", classes="strip-item")
        yield Static("gov:—", id="strip-gov", classes="strip-item")
        yield Badge("engine …", "dim", id="strip-engine")
        yield Static("", id="strip-home", classes="strip-item")
        yield Static("", id="strip-brain", classes="strip-item")
        yield Static(time.strftime("%H:%M:%S"), id="strip-clock", classes="strip-item")


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
        n_out = len([ln for ln in res.out_lines if ln.strip()])
        self.update(
            f"■ {res.label} · {res.duration:.2f}s · {n_out} line(s){note}"
        )


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


# agent label colors (mirrors the CLI's PALETTE idea, terminal-safe hex)
_AGENT_COLORS = [
    "#39bae6", "#f07178", "#3fd084", "#ffb454", "#d2a6ff",
    "#95e6cb", "#f26d78", "#aad94c", "#73d0ff", "#e6b673",
]


def agent_hex(name: str) -> str:
    h = 0
    for ch in str(name):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return _AGENT_COLORS[h % len(_AGENT_COLORS)]


class TurnEventPane(RichLog):
    """Live agent-turn renderer for run screens (debate/chat/community/teams).

    The CLI emits one NDJSON progress object per completed turn in ``--json``
    mode; this pane polls the engine taps and renders each as a chat-style
    block: colored agent header (model · round · latency) + wrapped text.
    Non-event JSON (final results) is kept for the screen's ``on_done``;
    stderr lines show as dim warnings so failures stay visible while running.
    """

    _POLL = 0.12

    def __init__(self, wrap_pad: int = 4, **kwargs: Any) -> None:
        super().__init__(markup=True, wrap=True, max_lines=4000, **kwargs)
        self._engine: Any = None
        self._timer: Any = None
        self._wrap_pad = wrap_pad

    # pane API shared with OutputPane ------------------------------------
    def bind_engine(self, engine: Any) -> None:
        self._engine = engine
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_interval(self._POLL, self._poll)

    def reset_stream(self) -> None:
        self.clear()

    def finalize(self, res: RunResult) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._engine = None

    # ------------------------------------------------------------------
    def _poll(self) -> None:
        if self._engine is None:
            return
        for line in self._engine.poll_err_lines():
            if line.strip():
                self.write(Text(line, style="dim"))
        for line in self._engine.poll_out_lines():
            self._render_stdout_line(line)

    def _render_stdout_line(self, line: str) -> None:
        line = (line or "").strip()
        if not line:
            return
        try:
            obj = json.loads(line)
        except Exception:
            self.write(Text(line, style="dim"))
            return
        if not isinstance(obj, dict):
            return
        if obj.get("event") == "turn":
            self.write_turn(
                agent=str(obj.get("agent") or "?"),
                text=str(obj.get("text") or ""),
                model=str(obj.get("model") or ""),
                provider=str(obj.get("provider") or ""),
                phase=str(obj.get("phase") or ""),
                team=str(obj.get("team") or ""),
                round_no=obj.get("round"),
                latency_ms=obj.get("latency_ms"),
                ok=bool(obj.get("ok", True)),
            )
        # anything else (final results) is handled by the screen's on_done

    def write_turn(
        self,
        agent: str,
        text: str,
        model: str = "",
        provider: str = "",
        phase: str = "",
        team: str = "",
        round_no: Any = None,
        latency_ms: Any = None,
        ok: bool = True,
    ) -> None:
        color = agent_hex(agent)
        bits = [b for b in (provider, model) if b]
        if team:
            bits.insert(0, team.upper())
        if round_no not in (None, "", 0):
            bits.append(f"round {round_no}")
        if phase:
            bits.append(phase)
        if latency_ms not in (None, ""):
            try:
                bits.append(f"{float(latency_ms):.0f} ms")
            except (TypeError, ValueError):
                pass
        meta = " · ".join(bits)
        mark = "✓" if ok else "✗"
        header = f"[bold {color}]▸ {agent}[/bold {color}]"
        if meta:
            header += f" [dim]· {meta} · {mark}[/dim]"
        self.write(header)
        width = max(28, (self.size.width or 80) - self._wrap_pad)
        for raw in (text or "").rstrip().split("\n"):
            for piece in (textwrap.wrap(raw, width) or [""]):
                self.write(piece)
        self.write("")


def brain_summary_from_status(out_text: str) -> Optional[str]:
    """One-line brain digest from ``brain status --json`` metrics table."""
    tables = parse_ndjson_tables(out_text)
    if not tables:
        return None
    metrics = {str(r.get("metric")): r.get("value") for r in tables[0]}
    if not metrics:
        return None
    return (
        f"{metrics.get('insights (active/total)', '—')} insights · "
        f"{metrics.get('sessions', '—')} sessions"
    )


# ---------------------------------------------------------------------------
# NDJSON / table helpers (schema-agnostic: the real CLI output is the truth)


def parse_ndjson_tables(text: str) -> List[List[Dict[str, Any]]]:
    """Parse stdout of ``--json`` mode preserving table boundaries.

    The CLI prints one compact JSON array (or object) per line; each line
    becomes one table of rows. ``brain status`` for example emits three
    arrays (metrics, genome, recent evolutions)."""
    tables: List[List[Dict[str, Any]]] = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            tables.append([obj])
        elif isinstance(obj, list):
            tables.append([r for r in obj if isinstance(r, dict)])
    return tables


def parse_ndjson(text: str) -> List[Dict[str, Any]]:
    """Parse NDJSON rows emitted by ``--json`` mode (stdout).

    Accepts one object per line *and* the one-JSON-array-per-table lines the
    CLI actually emits (flattened in order)."""
    rows: List[Dict[str, Any]] = []
    for table in parse_ndjson_tables(text):
        rows.extend(table)
    return rows


def parse_first_json(text: str) -> Optional[Dict[str, Any]]:
    """Tolerantly extract the first JSON object from free-form output.

    ``evolve stats`` pretty-prints a nested JSON document instead of NDJSON;
    this pulls it back out (string-aware brace matching)."""
    text = text or ""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                except Exception:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


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
    table.cursor_type = "row"
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


# ---------------------------------------------------------------------------
# fixed-column tables (brain screen)


def truncate(value: Any, width: int = 80) -> str:
    """One-line, width-capped cell text."""
    s = "" if value is None else str(value)
    s = s.replace("\n", " ")
    return s if len(s) <= width else s[: width - 1] + "…"


_NUMERIC_RE = re.compile(r"-?\d+(?:\.\d+)?")


def fmt_cell(value: Any, max_width: Optional[int] = None) -> Any:
    """Format one table cell for a fixed-column DataTable.

    Numeric values (and numeric-looking strings) are kept numeric so column
    sorting behaves numerically; long text is truncated to ``max_width``."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "✓" if value else "✗"
    if isinstance(value, (int, float)):
        return value
    s = str(value)
    if max_width is not None:
        return truncate(s, max_width)
    st = s.strip()
    if st and _NUMERIC_RE.fullmatch(st):
        f = float(st)
        return int(f) if f.is_integer() else f
    return s


def _col_spec(col: Sequence[Any]) -> Tuple[str, str, Optional[int]]:
    """Normalize a column spec to (key, header, max_width)."""
    if len(col) == 2:
        return col[0], col[1], None
    return col[0], col[1], col[2]


def populate_table_fixed(
    table: DataTable,
    rows: Sequence[Dict[str, Any]],
    cols: Sequence[Sequence[Any]],
) -> None:
    """Fill a DataTable with fixed (key, header[, max_width]) columns.

    Rows are keyed by their index so selection events can map back to the
    parsed record even after sorting."""
    table.cursor_type = "row"
    table.clear(columns=True)
    table.add_columns(*[_col_spec(c)[1] for c in cols])
    for i, row in enumerate(rows):
        table.add_row(
            *[fmt_cell(row.get(_col_spec(c)[0]), _col_spec(c)[2]) for c in cols],
            key=str(i),
        )


def rows_fingerprint(rows: Sequence[Dict[str, Any]]) -> str:
    """Stable digest of parsed rows — auto-refresh skips no-op repopulates."""
    payload = json.dumps(list(rows), sort_keys=True, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def export_rows(rows: Sequence[Dict[str, Any]], fmt: str, stem: str, home: Path) -> Optional[Path]:
    """Write parsed rows to ``<home>/exports/<stem>-<timestamp>.<fmt>``."""
    if not rows:
        return None
    out_dir = Path(home) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}.{fmt}"
    if fmt == "json":
        path.write_text(
            json.dumps(list(rows), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    elif fmt == "csv":
        fields: List[str] = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _fmt_cell(row.get(k)) for k in fields})
    else:
        return None
    return path


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
