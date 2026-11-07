"""Brain screen — status, insights, search, log, sessions, evolve, danger zone.

Every tab renders its data inline: dedicated DataTables / panels filled from
the real CLI's ``--json`` output (one JSON array per table on stdout), with
detail modals on row selection, click-to-sort columns, client-side filters,
per-tab auto-refresh (fingerprint-guarded so unchanged data never flickers),
JSON/CSV export, and previewed confirmations in the danger zone.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from raphael.multiagent.tui.engine import RunResult
from raphael.multiagent.tui.widgets import (
    export_rows,
    fmt_cell,
    parse_first_json,
    parse_ndjson,
    parse_ndjson_tables,
    populate_table_fixed,
    rows_fingerprint,
    truncate,
)
from raphael.multiagent.tui.screens.base import ConfirmModal, RaphaelScreen

# ---------------------------------------------------------------------------
# column specs: (json key, header, max width or None)
INSIGHT_COLS = [
    ("id", "ID", None),
    ("insight", "Insight", 60),
    ("conf", "Conf", None),
    ("weight", "Wt", None),
    ("used", "Used", None),
    ("✓/✗", "✓/✗", None),
    ("active", "Active", None),
    ("created", "Created", None),
]
SEARCH_COLS = [
    ("id", "ID", None),
    ("insight", "Insight", 56),
    ("conf", "Conf", None),
    ("sim", "Sim", None),
    ("relevance", "Relevance", None),
]
LOG_COLS = [
    ("at", "At", None),
    ("session", "Session", None),
    ("agent", "Agent", None),
    ("role", "Role", None),
    ("phase", "Phase", None),
    ("excerpt", "Excerpt", 54),
]
SESSION_COLS = [
    ("id", "ID", None),
    ("kind", "Kind", None),
    ("topic", "Topic", 32),
    ("mode", "Mode", None),
    ("started", "Started", 16),
    ("finished", "Finished", 16),
    ("verdict", "Verdict", 14),
]
EVO_COLS = [
    ("id", "ID", None),
    ("kind", "Kind", None),
    ("edits", "Edits", None),
    ("status", "Status", None),
    ("seen", "Seen", None),
    ("eval_after", "After", None),
    ("created", "Created", None),
    ("decided", "Decided", None),
    ("reason", "Reason", 26),
]
GENOME_COLS = [
    ("persona", "Persona", None),
    ("version", "Ver", None),
    ("origin", "Origin", 20),
    ("prompt_sha", "Prompt SHA", None),
]
STRATEGY_COLS = [("key", "Key", None), ("value", "Value", None)]
DIFF_COLS = [
    ("target", "Target", None),
    ("field", "Field", None),
    ("action", "Action", None),
    ("value", "Value", 46),
    ("reason", "Reason", 40),
]
STATUS_EVO_COLS = [
    ("id", "ID", None),
    ("status", "Status", None),
    ("reason", "Reason", 44),
    ("at", "At", None),
]

# tab pane id -> (auto checkbox id, interval input id, default seconds, refresher)
AUTO_TABS = {
    "pane-status": ("status-auto", "status-interval", 5, "_refresh_status"),
    "pane-insights": ("ins-auto", "ins-interval", 10, "_refresh_insights"),
    "pane-log": ("log-auto", "log-interval", 5, "_refresh_log"),
    "pane-sessions": ("sess-auto", "sess-interval", 30, "_refresh_sessions"),
    "pane-evolve": ("evo-auto", "evo-interval", 15, "_refresh_evolve_data"),
}

# export button stem -> (table id, file stem)
EXPORT_TARGETS = {
    "ins": ("insights-table", "insights"),
    "srch": ("srch-results", "search"),
    "log": ("log-table", "brain-log"),
    "sess": ("sess-table", "sessions"),
    "evo": ("evo-history", "evolutions"),
}


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any, default: int = 0) -> int:
    f = _as_float(value)
    return int(f) if f is not None else default


def _drop_placeholder(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The CLI prints `{"id": "(none)"}` for empty tables — drop those rows."""
    return [r for r in rows if str(r.get("id")) not in ("(none)", "—")]


# ---------------------------------------------------------------------------
# detail modals


class BrainDetailModal(ModalScreen):  # type: ignore[misc]
    """Common chrome for read-only record dialogs (Escape closes)."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def action_dismiss(self) -> None:
        self.dismiss(None)


class InsightDetailModal(BrainDetailModal):
    """Full insight text plus confidence / validation state."""

    def __init__(self, row: Dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._row = row

    def compose(self) -> ComposeResult:
        r = self._row
        with VerticalScroll(id="detail-dialog"):
            yield Static("insight", classes="section-label")
            yield Static(escape(str(r.get("insight") or r.get("text") or "(no text)")))
            yield Static("confidence & validation", classes="section-label")
            yield Static(
                escape(
                    "confidence {conf} · weight {wt} · active {act}\n"
                    "used {used} · confirmed/contradicted {val}\n"
                    "created {created} · updated {updated}\n"
                    "session {session}".format(
                        conf=r.get("conf", "—"),
                        wt=r.get("weight", "—"),
                        act=fmt_cell(r.get("active")),
                        used=r.get("used", "—"),
                        val=r.get("✓/✗", "—"),
                        created=r.get("created", "—"),
                        updated=r.get("updated", "—"),
                        session=r.get("session_id", "—"),
                    )
                )
            )
        yield Footer()


class SessionDetailModal(BrainDetailModal):
    """Session metadata with a transcript viewer fed by ``brain log --session``."""

    def __init__(
        self,
        row: Dict[str, Any],
        on_load_turns: Callable[[str], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._row = row
        self._on_load_turns = on_load_turns

    def compose(self) -> ComposeResult:
        r = self._row
        with VerticalScroll(id="detail-dialog"):
            yield Static("session", classes="section-label")
            yield Static(
                escape(
                    "{sid}\nkind {kind} · mode {mode}\ntopic {topic}\n"
                    "started {started} · finished {finished}\nverdict {verdict}".format(
                        sid=r.get("id", "—"),
                        kind=r.get("kind", "—"),
                        mode=r.get("mode", "—"),
                        topic=r.get("topic", "—"),
                        started=r.get("started", "—"),
                        finished=r.get("finished", "—"),
                        verdict=r.get("verdict", "—"),
                    )
                )
            )
            with Horizontal():
                yield Button("Load transcript turns", id="detail-load-turns")
            yield Label("transcript (brain log --session)", classes="section-label")
            yield RichLog(id="detail-log", markup=False, wrap=True, max_lines=2000)
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "detail-load-turns":
            self._on_load_turns(str(self._row.get("id") or ""))

    def set_turns(self, rows: Sequence[Dict[str, Any]]) -> None:
        log = self.query_one("#detail-log", RichLog)
        log.clear()
        if not rows:
            log.write("(no turns recorded for this session)")
            return
        for r in rows:
            log.write(
                f"[{truncate(r.get('at'), 19)}] {r.get('agent', '—')}/{r.get('role', '—')}"
                f" · {r.get('phase', '—')}"
            )
            log.write(truncate(r.get("content") or r.get("excerpt"), 2000))
            log.write("")


class EvolutionDetailModal(BrainDetailModal):
    """Evolution record; optionally acts as the rollback confirmation."""

    def __init__(self, row: Dict[str, Any], confirm: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._row = row
        self._confirm = confirm

    def compose(self) -> ComposeResult:
        r = self._row
        with VerticalScroll(id="detail-dialog"):
            yield Static(f"evolution #{r.get('id', '—')}", classes="section-label")
            yield Static(
                escape(
                    "kind {kind} · status {status}\ncreated {created} · decided {decided}\n"
                    "progress {seen}/{after} sessions seen (evaluation gate)\nreason {reason}".format(
                        kind=r.get("kind", "—"),
                        status=r.get("status", "—"),
                        created=r.get("created", "—"),
                        decided=r.get("decided", "—"),
                        seen=r.get("seen", "—"),
                        after=r.get("eval_after", "—"),
                        reason=r.get("reason") or "(none recorded)",
                    )
                )
            )
            yield Static("edits", classes="section-label")
            edits = r.get("edit_list") if isinstance(r.get("edit_list"), list) else []
            if edits:
                for e in edits:
                    if not isinstance(e, dict):
                        continue
                    yield Static(
                        escape(
                            f"• {e.get('target', '?')} · {e.get('field', '?')} · "
                            f"{e.get('action', '?')}\n  value: {truncate(e.get('value'), 90)}\n"
                            f"  reason: {truncate(e.get('reason'), 90)}"
                        )
                    )
            else:
                n = r.get("edits", "—")
                yield Static(escape(f"{n} edit(s) — run `brain evolutions` for full payloads"))
            if self._confirm:
                yield Static(escape(self._confirm), classes="section-label")
                with Horizontal():
                    yield Button("Confirm rollback", id="detail-yes", variant="error")
                    yield Button("Cancel", id="detail-no")
            else:
                with Horizontal():
                    yield Button("Close", id="detail-no")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "detail-yes":
            self.dismiss(True)
        elif event.button.id == "detail-no":
            self.dismiss(False)


# ---------------------------------------------------------------------------
# the screen


class BrainScreen(RaphaelScreen):
    TITLE = "raphael-ma · brain"
    SHOWS_BRAIN_STRIP = True

    BINDINGS = [
        Binding("r", "refresh_tab", "Refresh tab"),
        Binding("x", "export_csv", "Export CSV"),
        Binding("j", "export_json", "Export JSON"),
    ]

    # ------------------------------------------------------------------
    def compose_body(self) -> ComposeResult:
        with TabbedContent(id="brain-tabs"):
            with TabPane("Status", id="pane-status"):
                with Horizontal(classes="form-row"):
                    yield Button("Refresh", id="btn-status")
                    yield Checkbox("auto", id="status-auto", value=True)
                    yield Label("every")
                    yield Input("5", id="status-interval", type="integer", classes="narrow")
                    yield Label("s")
                yield Static("(loading brain status …)", id="status-panel", classes="status-panel")
                yield Label("genome (active personas)", classes="section-label")
                yield DataTable(id="status-genome-table", classes="mini-table")
                yield Label("recent evolutions", classes="section-label")
                yield DataTable(id="status-evo-table", classes="mini-table")
            with TabPane("Insights", id="pane-insights"):
                with Horizontal(classes="form-row"):
                    yield Label("scope")
                    yield Select([("active", "active"), ("all", "all")], value="active", id="ins-scope")
                    yield Label("limit")
                    yield Input("20", id="ins-limit", type="integer", classes="narrow")
                    yield Button("Load insights", id="btn-insights")
                    yield Checkbox("auto", id="ins-auto", value=False)
                    yield Label("every")
                    yield Input("10", id="ins-interval", type="integer", classes="narrow")
                    yield Label("s")
                with Horizontal(classes="form-row"):
                    yield Label("filter")
                    yield Input(placeholder="substring filter (id or text)", id="ins-filter")
                    yield Button("export csv", id="btn-ins-csv")
                    yield Button("export json", id="btn-ins-json")
                yield DataTable(id="insights-table")
            with TabPane("Search", id="pane-search"):
                with Horizontal(classes="form-row"):
                    yield Label("query")
                    yield Input(placeholder="vector recall query", id="srch-query")
                with Horizontal(classes="form-row"):
                    yield Label("top-k")
                    yield Input("5", id="srch-k", type="integer", classes="narrow")
                    yield Button("Search", id="btn-search")
                    yield Button("export csv", id="btn-srch-csv")
                    yield Button("export json", id="btn-srch-json")
                yield Static("relevance = similarity × confidence", id="srch-hint")
                yield DataTable(id="srch-results")
            with TabPane("Log", id="pane-log"):
                with Horizontal(classes="form-row"):
                    yield Label("last")
                    yield Input("20", id="log-last", type="integer", classes="narrow")
                    yield Label("offset")
                    yield Input("0", id="log-offset", type="integer", classes="narrow")
                    yield Label("session")
                    yield Input(placeholder="session id (optional)", id="log-session")
                with Horizontal(classes="form-row"):
                    yield Label("agent")
                    yield Input(placeholder="agent filter", id="log-agent")
                    yield Label("phase")
                    yield Input(placeholder="phase filter", id="log-phase")
                    yield Button("Load log", id="btn-log")
                    yield Checkbox("auto", id="log-auto", value=False)
                    yield Label("every")
                    yield Input("5", id="log-interval", type="integer", classes="narrow")
                    yield Label("s")
                with Horizontal(classes="form-row"):
                    yield Button("export csv", id="btn-log-csv")
                    yield Button("export json", id="btn-log-json")
                yield DataTable(id="log-table")
            with TabPane("Sessions", id="pane-sessions"):
                with Horizontal(classes="form-row"):
                    yield Label("limit")
                    yield Input("20", id="sess-limit", type="integer", classes="narrow")
                    yield Label("offset")
                    yield Input("0", id="sess-offset", type="integer", classes="narrow")
                    yield Button("Load sessions", id="btn-sessions")
                    yield Checkbox("auto", id="sess-auto", value=False)
                    yield Label("every")
                    yield Input("30", id="sess-interval", type="integer", classes="narrow")
                    yield Label("s")
                with Horizontal(classes="form-row"):
                    yield Button("export csv", id="btn-sess-csv")
                    yield Button("export json", id="btn-sess-json")
                yield DataTable(id="sess-table")
            with TabPane("Evolve", id="pane-evolve"):
                with Horizontal(classes="form-row"):
                    yield Button("evolve stats", id="btn-evolve-stats")
                    yield Button("evolve evaluate", id="btn-evolve-evaluate")
                    yield Checkbox("dry-run", id="evolve-dry", value=True)
                    yield Button("evolve run", id="btn-evolve-run", variant="warning")
                    yield Checkbox("auto", id="evo-auto", value=False)
                    yield Label("every")
                    yield Input("15", id="evo-interval", type="integer", classes="narrow")
                    yield Label("s")
                yield Static("no pending evolutions — the current genome is stable", id="evolve-pending")
                with Horizontal(classes="form-row"):
                    yield Label("evolution history", classes="section-label")
                    yield Button("export csv", id="btn-evo-csv")
                    yield Button("export json", id="btn-evo-json")
                yield DataTable(id="evo-history")
                with Horizontal(id="evo-genome-row"):
                    yield DataTable(id="evolve-genome-table", classes="mini-table")
                    yield DataTable(id="evolve-strategy-table", classes="mini-table")
                yield Label("evolver performance stats", classes="section-label")
                yield Static("(run evolve stats)", id="evolve-stats")
                yield Label("last dry-run proposal (diff view)", classes="section-label")
                yield Static("(no dry-run yet)", id="evolve-diff")
                yield DataTable(id="evolve-diff-table", classes="mini-table")
            with TabPane("Danger", id="pane-danger"):
                with Horizontal(classes="form-row"):
                    yield Label("evolution id")
                    yield Input(placeholder="evolution_id", id="rb-id")
                    yield Button("brain rollback", id="btn-rollback", classes="danger")
                with Horizontal(classes="form-row"):
                    yield Button("brain reset", id="btn-reset", classes="danger")
                with Horizontal(classes="form-row"):
                    yield Label("session.json")
                    yield Input(placeholder="path/to/session.json", id="imp-path")
                    yield Label("session id")
                    yield Input(placeholder="optional --session-id", id="imp-sid")
                    yield Button("brain import", id="btn-import")
                yield Static(
                    "rollback previews the evolution before confirming · reset shows what "
                    "will be wiped · import previews the file first",
                    classes="hint-label",
                )
        yield Label(
            "click a column header to sort · click a row for details · rows come from "
            "raphael-ma --json (the real CLI output is the truth)",
            classes="hint-label",
        )

    # ------------------------------------------------------------------
    def on_mount(self) -> None:
        self._rows: Dict[str, List[Dict[str, Any]]] = {}
        self._fp: Dict[str, str] = {}
        self._sort_state: Dict[str, tuple] = {}
        self._auto_last: Dict[str, float] = {}
        self._loaded_panes: set = set()
        self._pending_loads: set = set()
        self._all_insights: List[Dict[str, Any]] = []
        self._all_log: List[Dict[str, Any]] = []
        self._status_metrics: Dict[str, Any] = {}
        self._session_modal: Optional[SessionDetailModal] = None
        self.set_interval(1.0, self._tick_auto)
        self._refresh_status()

    # pane id -> lazy loader (first activation loads the data inline)
    _LAZY_LOADERS = {
        "pane-insights": "_refresh_insights",
        "pane-log": "_refresh_log",
        "pane-sessions": "_refresh_sessions",
        "pane-evolve": "_refresh_evolve_data",
    }

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Lazy initial load: activate a never-loaded tab → fetch its data.

        If a command happens to be running mid-switch the request is queued
        and drained by the auto tick — never silently dropped."""
        pane_id = (event.pane.id or "") if event.pane is not None else ""
        if pane_id and pane_id not in self._loaded_panes:
            self._pending_loads.add(pane_id)
        self._drain_pending_loads()

    def _drain_pending_loads(self) -> None:
        if self.app.state.busy:  # type: ignore[attr-defined]
            return
        for pane_id in sorted(self._pending_loads):
            method_name = self._LAZY_LOADERS.get(pane_id)
            if method_name is None:
                self._pending_loads.discard(pane_id)
                continue
            self._pending_loads.discard(pane_id)
            getattr(self, method_name)()
            return  # one command at a time; next tick drains the rest

    def refresh_on_show(self) -> None:
        super().refresh_on_show()
        # returning to the brain screen: force the active tab's auto-refresh
        self._auto_last.clear()

    # ------------------------------------------------------------------
    # helpers
    def _active_tab(self) -> str:
        try:
            pane = self.query_one("#brain-tabs", TabbedContent).active_pane
            return pane.id or ""
        except Exception:
            return ""

    def _resolve_table(self, table_id: str) -> DataTable:
        """query_one by id with a depth-first fallback.

        Textual's id-index fast path can miss widgets inside a TabPane whose
        index registration has not settled yet (seen with freshly activated
        panes); the type scan keeps command callbacks working regardless.
        """
        try:
            return self.query_one(f"#{table_id}", DataTable)
        except Exception:
            for table in self.query(DataTable):
                if table.id == table_id:
                    return table
            raise

    def _populate(self, table_id: str, rows: List[Dict[str, Any]], cols: Sequence[Sequence[Any]]) -> bool:
        """Cache + populate a table; skip the rebuild when data is unchanged."""
        self._rows[table_id] = rows
        fp = rows_fingerprint(rows)
        if self._fp.get(table_id) == fp:
            return False
        self._fp[table_id] = fp
        populate_table_fixed(self._resolve_table(table_id), rows, cols)
        return True

    def _tick_auto(self) -> None:
        # queued lazy loads always take priority over periodic refreshes
        if self._pending_loads:
            self._drain_pending_loads()
            return
        state = self.app.state  # type: ignore[attr-defined]
        if state.busy:
            return
        pane_id = self._active_tab()
        spec = AUTO_TABS.get(pane_id)
        if spec is None:
            return
        cb_id, int_id, default, method_name = spec
        if not self._value(f"#{cb_id}", default=False):
            return
        try:
            interval = max(2, int(float(self._value(f"#{int_id}") or default)))
        except (TypeError, ValueError):
            interval = default
        now = time.monotonic()
        if now - self._auto_last.get(pane_id, 0.0) < interval:
            return
        self._auto_last[pane_id] = now
        getattr(self, method_name)(background=True)

    # ------------------------------------------------------------------
    # Status tab
    def _refresh_status(self, background: bool = False) -> None:
        self._loaded_panes.add("pane-status")
        self.run_command(
            ["brain", "status"],
            json_mode=True,
            label="brain status",
            background=background,
            on_done=self._render_status,
        )

    def _render_status(self, res: RunResult) -> None:
        if not res.ok:
            return
        tables = parse_ndjson_tables(res.out)
        if not tables:
            return
        metrics = {str(r.get("metric")): r.get("value") for r in tables[0]}
        self._status_metrics = metrics
        self.query_one("#status-panel", Static).update(self._status_markup(metrics))
        self._populate(
            "status-genome-table",
            tables[1] if len(tables) > 1 else [],
            GENOME_COLS,
        )
        self._populate(
            "status-evo-table",
            tables[2] if len(tables) > 2 else [],
            STATUS_EVO_COLS,
        )
        state = self.app.state  # type: ignore[attr-defined]
        state.brain_summary = (
            f"{metrics.get('insights (active/total)', '—')} insights · "
            f"{metrics.get('sessions', '—')} sessions"
        )
        self.refresh_strip()

    @staticmethod
    def _status_markup(m: Dict[str, Any]) -> str:
        def kv(key: str, value: Any) -> str:
            return f"[bold]  {key:<20}[/bold] {escape(str(value))}"

        return "\n".join(
            [
                "[bold]brain database[/bold]",
                kv("path", m.get("db path", "—")),
                kv("size / wal / mode", f"{m.get('db size', '—')} · {m.get('wal', '—')} · {m.get('mode', '—')}"),
                "[bold]memory[/bold]",
                kv("sessions", f"{m.get('active sessions', '—')} active / {m.get('sessions', '—')} total · {m.get('journal turns', '—')} turns"),
                kv("insights", f"{m.get('insights (active/total)', '—')} active · conf {m.get('avg insight confidence', '—')} · ✓/✗ {m.get('insights confirmed/contradicted', '—')}"),
                kv("outcomes", m.get("outcomes", "—")),
                "[bold]evolution[/bold]",
                kv("evolutions", f"{m.get('evolutions (total/active)', '—')} active · last {m.get('last evolution', '—')}"),
                kv("genome hash", m.get("genome hash", "—")),
            ]
        )

    # ------------------------------------------------------------------
    # Insights tab
    def _refresh_insights(self, background: bool = False) -> None:
        self._loaded_panes.add("pane-insights")
        scope = self._value("#ins-scope") or "active"
        limit = (self._value("#ins-limit") or "20").strip() or "20"
        argv = ["brain", "insights", "--limit", limit]
        argv.append("--all" if scope == "all" else "--active")
        self.run_command(
            argv,
            json_mode=True,
            label="brain insights",
            background=background,
            on_done=self._render_insights,
        )

    def _render_insights(self, res: RunResult) -> None:
        if not res.ok:
            return
        self._all_insights = _drop_placeholder(parse_ndjson(res.out))
        self._apply_insight_filter()

    def _apply_insight_filter(self) -> None:
        term = str(self._value("#ins-filter") or "").strip().lower()
        rows = self._all_insights
        if term:
            rows = [
                r for r in rows
                if term in str(r.get("insight", "")).lower() or term in str(r.get("id"))
            ]
        self._populate("insights-table", rows, INSIGHT_COLS)

    # ------------------------------------------------------------------
    # Search tab
    def _run_search(self, background: bool = False) -> None:
        query = str(self._value("#srch-query") or "").strip()
        if not query:
            self.app.notify("Search needs a query.", title="Brain", severity="warning")
            return
        k = (self._value("#srch-k") or "5").strip() or "5"
        self._last_query = query
        self.run_command(
            ["brain", "search", query, "-k", k],
            json_mode=True,
            label="brain search",
            background=background,
            on_done=self._render_search,
        )

    def _render_search(self, res: RunResult) -> None:
        if not res.ok:
            return
        enriched: List[Dict[str, Any]] = []
        for r in _drop_placeholder(parse_ndjson(res.out)):
            conf = _as_float(r.get("conf"))
            sim = _as_float(r.get("sim"))
            row = dict(r)
            row["relevance"] = round(conf * sim, 3) if conf is not None and sim is not None else "—"
            enriched.append(row)
        enriched.sort(
            key=lambda r: r["relevance"] if isinstance(r.get("relevance"), (int, float)) else -1.0,
            reverse=True,
        )
        self._populate("srch-results", enriched, SEARCH_COLS)
        self.query_one("#srch-hint", Static).update(
            escape(f"{len(enriched)} match(es) for '{self._last_query}' · relevance = sim × conf")
        )

    # ------------------------------------------------------------------
    # Log tab
    def _refresh_log(self, background: bool = False) -> None:
        self._loaded_panes.add("pane-log")
        last = (self._value("#log-last") or "20").strip() or "20"
        argv = ["brain", "log", "--last", last]
        offset = (self._value("#log-offset") or "0").strip()
        if offset and offset != "0":
            argv += ["--offset", offset]
        session = str(self._value("#log-session") or "").strip()
        if session:
            argv += ["--session", session]
        self.run_command(
            argv,
            json_mode=True,
            label="brain log",
            background=background,
            on_done=self._render_log,
        )

    def _render_log(self, res: RunResult) -> None:
        if not res.ok:
            return
        # CLI emits latest-first; flip so the newest entry sits at the bottom
        self._all_log = list(reversed(_drop_placeholder(parse_ndjson(res.out))))
        self._apply_log_filter()

    def _apply_log_filter(self) -> None:
        agent = str(self._value("#log-agent") or "").strip().lower()
        phase = str(self._value("#log-phase") or "").strip().lower()
        rows = self._all_log
        if agent:
            rows = [r for r in rows if agent in str(r.get("agent", "")).lower()]
        if phase:
            rows = [r for r in rows if phase in str(r.get("phase", "")).lower()]
        changed = self._populate("log-table", rows, LOG_COLS)
        if changed:
            self._resolve_table("log-table").scroll_end(animate=False)

    # ------------------------------------------------------------------
    # Sessions tab
    def _refresh_sessions(self, background: bool = False) -> None:
        self._loaded_panes.add("pane-sessions")
        limit = (self._value("#sess-limit") or "20").strip() or "20"
        argv = ["brain", "sessions", "--limit", limit]
        offset = (self._value("#sess-offset") or "0").strip()
        if offset and offset != "0":
            argv += ["--offset", offset]
        self.run_command(
            argv,
            json_mode=True,
            label="brain sessions",
            background=background,
            on_done=self._render_sessions,
        )

    def _render_sessions(self, res: RunResult) -> None:
        if not res.ok:
            return
        self._populate("sess-table", _drop_placeholder(parse_ndjson(res.out)), SESSION_COLS)

    # ------------------------------------------------------------------
    # Evolve tab
    def _refresh_evolve_data(self, background: bool = False) -> None:
        self._loaded_panes.add("pane-evolve")
        self.run_command(
            ["brain", "evolutions", "--limit", "50"],
            json_mode=True,
            label="brain evolutions",
            background=background,
            on_done=self._render_evolve_history,
        )

    def _render_evolve_history(self, res: RunResult) -> None:
        if res.ok:
            rows = _drop_placeholder(parse_ndjson(res.out))
            self._populate("evo-history", rows, EVO_COLS)
            self._render_pending(rows)
        self.run_command(
            ["brain", "genome"],
            json_mode=True,
            label="brain genome",
            background=True,
            on_done=self._render_genome,
        )

    def _render_genome(self, res: RunResult) -> None:
        if res.ok:
            tables = parse_ndjson_tables(res.out)
            self._populate("evolve-genome-table", tables[0] if tables else [], GENOME_COLS)
            self._populate(
                "evolve-strategy-table",
                tables[1] if len(tables) > 1 else [],
                STRATEGY_COLS,
            )
        self.run_command(
            ["evolve", "stats"],
            json_mode=True,
            label="evolve stats",
            background=True,
            on_done=self._render_evolve_stats,
        )

    def _render_evolve_stats(self, res: RunResult) -> None:
        if not res.ok:
            return
        stats = parse_first_json(res.out)
        if not stats:
            return
        lines = [f"[bold]sessions[/bold] {escape(str(stats.get('sessions_total', '—')))}"]
        personas = stats.get("persona_scores") or {}
        if personas:
            lines.append("[bold]persona scores[/bold]")
            for role, s in sorted(personas.items()):
                if isinstance(s, dict):
                    lines.append(
                        f"  {escape(str(role)):<12} mean {s.get('mean_score', '—')} · n={s.get('n_scores', '—')}"
                    )
        providers = stats.get("providers") or {}
        if providers:
            lines.append("[bold]providers[/bold]")
            for name, s in sorted(providers.items()):
                if isinstance(s, dict):
                    lines.append(
                        f"  {escape(str(name)):<14} {s.get('turns', '—')} turns · "
                        f"{s.get('avg_latency_ms', '—')} ms avg · {s.get('failed', '—')} failed"
                    )
        ins = stats.get("insights") or {}
        if ins:
            lines.append(
                "[bold]insights[/bold]  total {t} · active {a} · avg conf {c} · ✓/✗ {cf}/{x}".format(
                    t=ins.get("total", "—"),
                    a=ins.get("active", "—"),
                    c=ins.get("avg_confidence", "—"),
                    cf=ins.get("confirmed", "—"),
                    x=ins.get("contradicted", "—"),
                )
            )
        self.query_one("#evolve-stats", Static).update("\n".join(lines))

    def _render_pending(self, rows: Sequence[Dict[str, Any]]) -> None:
        active = [r for r in rows if str(r.get("status")) == "active"]
        lines = []
        for r in active:
            seen = _as_int(r.get("seen"))
            after = max(1, _as_int(r.get("eval_after"), 1))
            filled = min(seen, after)
            width = 14
            bar = "█" * round(filled / after * width) + "░" * (width - round(filled / after * width))
            lines.append(
                f"#{r.get('id', '?')} [{bar}] {seen}/{after} sessions · {truncate(r.get('reason'), 48)}"
            )
        self.query_one("#evolve-pending", Static).update(
            "\n".join(lines) if lines else "no pending evolutions — the current genome is stable"
        )

    def _run_evolve(self) -> None:
        argv = ["evolve", "run"]
        if self._value("#evolve-dry", default=True):
            argv.append("--dry-run")
        argv += list(self.mode_flags())
        self.run_command(argv, json_mode=True, label="evolve run", on_done=self._render_evolve_run)

    def _render_evolve_run(self, res: RunResult) -> None:
        if res.ok:
            tables = parse_ndjson_tables(res.out)
            rows = next(
                (t for t in tables if t and "target" in t[0]),
                tables[0] if tables else [],
            )
            self._populate("evolve-diff-table", rows, DIFF_COLS)
            diff_lines = []
            for e in rows:
                action = str(e.get("action", "set"))
                marker = "+" if action == "append" else ("~" if action == "replace" else "·")
                diff_lines.append(
                    f"{marker} {e.get('target', '?')}.{e.get('field', '?')} = {truncate(e.get('value'), 56)}"
                )
            self.query_one("#evolve-diff", Static).update(
                "\n".join(diff_lines) if diff_lines else "(the evolver proposed no valid edits)"
            )
        # history / genome / stats may have moved — refresh them quietly
        self._refresh_evolve_data(background=True)

    # ------------------------------------------------------------------
    # Danger zone (previewed confirmations)
    def _find_evolution(self, evolution_id: str) -> Optional[Dict[str, Any]]:
        for r in self._rows.get("evo-history", []):
            if str(r.get("id")) == str(evolution_id):
                return r
        return None

    def _preview_rollback(self, evolution_id: str) -> None:
        row = self._find_evolution(evolution_id)
        if row is not None:
            self._push_rollback_modal(row)
            return
        # history not loaded yet — fetch it, then preview
        self.run_command(
            ["brain", "evolutions", "--limit", "200"],
            json_mode=True,
            label="brain evolutions",
            on_done=lambda res: self._rollback_after_fetch(res, evolution_id),
        )

    def _rollback_after_fetch(self, res: RunResult, evolution_id: str) -> None:
        if res.ok:
            rows = _drop_placeholder(parse_ndjson(res.out))
            self._populate("evo-history", rows, EVO_COLS)
        row = self._find_evolution(evolution_id)
        if row is None:
            self.app.notify(
                f"Evolution #{evolution_id} not found in history.",
                title="Brain",
                severity="error",
            )
            return
        self._push_rollback_modal(row)

    def _push_rollback_modal(self, row: Dict[str, Any]) -> None:
        eid = str(row.get("id"))
        self.app.push_screen(
            EvolutionDetailModal(
                row,
                confirm=(
                    "Rolling back reverts these persona/strategy edits and restores the "
                    "previous genome. This cannot be undone from here."
                ),
            ),
            callback=lambda ok: self._rollback(ok, eid),
        )

    def _rollback(self, ok: bool, evolution_id: str) -> None:
        if not ok:
            return
        self.run_command(
            ["brain", "rollback", evolution_id],
            label="brain rollback",
            on_done=lambda res: self._refresh_evolve_data(background=res.ok),
        )

    def _preview_reset(self) -> None:
        self.run_command(
            ["brain", "status"],
            json_mode=True,
            label="brain status",
            on_done=self._confirm_reset,
        )

    def _confirm_reset(self, res: RunResult) -> None:
        m = self._status_metrics
        if res.ok:
            tables = parse_ndjson_tables(res.out)
            if tables:
                m = {str(r.get("metric")): r.get("value") for r in tables[0]}
        message = (
            "Reset the brain? This wipes:\n"
            f"  sessions      {m.get('sessions', '—')}\n"
            f"  journal turns {m.get('journal turns', '—')}\n"
            f"  insights      {m.get('insights (active/total)', '—')}\n"
            f"  outcomes      {m.get('outcomes', '—')}\n"
            f"  evolutions    {m.get('evolutions (total/active)', '—')}\n"
            "Persona genomes return to seed v1. Config is kept."
        )
        self.app.push_screen(ConfirmModal(message), callback=self._reset)

    def _reset(self, ok: bool) -> None:
        if not ok:
            return

        def after(res: RunResult) -> None:
            if not res.ok:
                return
            # wipe every cached view so the tables don't show stale rows
            self._all_insights = []
            self._all_log = []
            for table_id in list(self._rows):
                self._populate(table_id, [], self._cols_for(table_id))
            self._refresh_status(background=True)

        self.run_command(["brain", "reset", "--yes"], label="brain reset", on_done=after)

    @staticmethod
    def _cols_for(table_id: str) -> Sequence[Sequence[Any]]:
        return {
            "insights-table": INSIGHT_COLS,
            "srch-results": SEARCH_COLS,
            "log-table": LOG_COLS,
            "sess-table": SESSION_COLS,
            "evo-history": EVO_COLS,
            "status-genome-table": GENOME_COLS,
            "status-evo-table": STATUS_EVO_COLS,
            "evolve-genome-table": GENOME_COLS,
            "evolve-strategy-table": STRATEGY_COLS,
            "evolve-diff-table": DIFF_COLS,
        }.get(table_id, [])

    def _preview_import(self) -> None:
        path_s = str(self._value("#imp-path") or "").strip()
        if not path_s:
            self.app.notify("Import needs a session.json path.", title="Brain", severity="warning")
            return
        path = Path(path_s).expanduser()
        try:
            size = path.stat().st_size
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            self.app.notify(f"Cannot read {path}: {exc}", title="Brain", severity="error")
            return
        except json.JSONDecodeError as exc:
            self.app.notify(f"{path} is not valid JSON: {exc}", title="Brain", severity="error")
            return
        if not isinstance(data, dict):
            self.app.notify(f"{path} must hold a JSON object, got {type(data).__name__}.",
                            title="Brain", severity="error")
            return
        turns = data.get("turns") or []
        insights = data.get("insights") or []
        sid = str(self._value("#imp-sid") or "").strip() or data.get("session_id") or data.get("id") or "(auto)"
        message = (
            f"Import session from {path}?\n"
            f"  kind: {data.get('kind', 'imported')} · topic: {truncate(data.get('topic'), 48)}\n"
            f"  turns: {len(turns)} · insights: {len(insights)} · {size / 1024:.1f} KiB\n"
            f"  session id: {sid}"
        )
        self.app.push_screen(ConfirmModal(message), callback=self._import)

    def _import(self, ok: bool) -> None:
        if not ok:
            return
        path = str(self._value("#imp-path") or "").strip()
        argv = ["brain", "import", path]
        sid = str(self._value("#imp-sid") or "").strip()
        if sid:
            argv += ["--session-id", sid]
        self.run_command(
            argv,
            label="brain import",
            on_done=lambda res: self._refresh_sessions(background=res.ok) if res.ok else None,
        )

    # ------------------------------------------------------------------
    # export
    def _export(self, stem: str, fmt: str) -> None:
        target = EXPORT_TARGETS.get(stem)
        if target is None:
            return
        table_id, name = target
        rows = self._rows.get(table_id) or []
        if not rows:
            self.app.notify(
                "Nothing to export — load data first.", title="Export", severity="warning"
            )
            return
        path = export_rows(rows, fmt, name, self.app.state.home_path)  # type: ignore[attr-defined]
        if path is not None:
            self.app.notify(f"Exported {len(rows)} rows → {path}", title="Export")
        else:
            self.app.notify(f"Unknown export format: {fmt}", title="Export", severity="error")

    def _export_active_tab(self, fmt: str) -> None:
        stem_for_tab = {
            "pane-insights": "ins",
            "pane-search": "srch",
            "pane-log": "log",
            "pane-sessions": "sess",
            "pane-evolve": "evo",
        }.get(self._active_tab())
        if stem_for_tab is None:
            self.app.notify(
                "This tab has no exportable table.", title="Export", severity="warning"
            )
            return
        self._export(stem_for_tab, fmt)

    # ------------------------------------------------------------------
    # actions (keybindings)
    def action_refresh_tab(self) -> None:
        method = {
            "pane-status": self._refresh_status,
            "pane-insights": self._refresh_insights,
            "pane-search": self._run_search,
            "pane-log": self._refresh_log,
            "pane-sessions": self._refresh_sessions,
            "pane-evolve": self._refresh_evolve_data,
        }.get(self._active_tab())
        if method is not None:
            method()

    def action_export_csv(self) -> None:
        self._export_active_tab("csv")

    def action_export_json(self) -> None:
        self._export_active_tab("json")

    # ------------------------------------------------------------------
    # events
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("btn-") and bid.endswith(("-csv", "-json")):
            self._export(bid[4:-4], "csv" if bid.endswith("-csv") else "json")
            return
        if bid == "btn-status":
            self._refresh_status()
        elif bid == "btn-insights":
            self._refresh_insights()
        elif bid == "btn-search":
            self._run_search()
        elif bid == "btn-log":
            self._refresh_log()
        elif bid == "btn-sessions":
            self._refresh_sessions()
        elif bid == "btn-evolve-stats":
            self.run_command(
                ["evolve", "stats"],
                json_mode=True,
                label="evolve stats",
                on_done=self._render_evolve_stats,
            )
        elif bid == "btn-evolve-evaluate":
            self.run_command(
                ["evolve", "evaluate"],
                json_mode=True,
                label="evolve evaluate",
                on_done=lambda res: self._refresh_evolve_data(background=res.ok) if res.ok else None,
            )
        elif bid == "btn-evolve-run":
            self._run_evolve()
        elif bid == "btn-rollback":
            evolution_id = str(self._value("#rb-id") or "").strip()
            if not evolution_id:
                self.app.notify(
                    "Rollback needs an evolution id.", title="Brain", severity="warning"
                )
                return
            self._preview_rollback(evolution_id)
        elif bid == "btn-reset":
            self._preview_reset()
        elif bid == "btn-import":
            self._preview_import()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "ins-filter":
            self._apply_insight_filter()
        elif event.input.id in ("log-agent", "log-phase"):
            self._apply_log_filter()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Click-to-sort: toggle ascending/descending per column."""
        table = event.data_table
        tid = table.id or ""
        col = event.column_key
        prev = self._sort_state.get(tid)
        reverse = False if prev is None or prev[0] != col else not prev[1]
        self._sort_state[tid] = (col, reverse)
        table.sort(col, reverse=reverse)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = event.data_table
        tid = table.id or ""
        try:
            idx = int(event.row_key.value or -1)
        except (TypeError, ValueError):
            return
        rows = self._rows.get(tid) or []
        if idx < 0 or idx >= len(rows):
            return
        row = rows[idx]
        if tid == "insights-table":
            self.app.push_screen(InsightDetailModal(row))
        elif tid == "srch-results":
            self.app.push_screen(InsightDetailModal(row))
        elif tid == "sess-table":
            modal = SessionDetailModal(row, on_load_turns=self._load_session_turns)
            self._session_modal = modal
            self.app.push_screen(modal, callback=lambda _: self._forget_session_modal())
        elif tid in ("evo-history", "status-evo-table"):
            if tid == "status-evo-table":
                full = self._find_evolution(str(row.get("id")))
                row = full if full is not None else row
            self.app.push_screen(EvolutionDetailModal(row))

    def _forget_session_modal(self) -> None:
        self._session_modal = None

    def _load_session_turns(self, session_id: str) -> None:
        if not session_id:
            return
        modal = self._session_modal

        def done(res: RunResult) -> None:
            rows = list(reversed(parse_ndjson(res.out))) if res.ok else []
            if modal is not None and modal.is_mounted:
                modal.set_turns(rows)

        self.run_command(
            ["brain", "log", "--last", "200", "--session", session_id, "--full"],
            json_mode=True,
            label="session turns",
            on_done=done,
        )
