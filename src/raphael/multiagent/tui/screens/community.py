"""Community debate screen — specialists, moderator synthesis, scoring.

v2: the round-table runs in ``--json`` mode with every agent turn rendered
live into a dedicated pane (colored per-agent headers, model · round ·
latency meta). When the CLI finishes, the moderator synthesis, consensus /
dissent / open questions and the per-agent score table are rendered inline;
past round-tables can be reopened from the history table (click a row for
the session detail modal with its transcript).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, Select, Static

from raphael.multiagent.tui.engine import RunResult
from raphael.multiagent.tui.screens.base import RaphaelScreen
from raphael.multiagent.tui.screens.brain import SessionDetailModal
from raphael.multiagent.tui.widgets import (
    CommandBar,
    OutputPane,
    ResultBanner,
    StatusStrip,
    TurnEventPane,
    parse_ndjson,
    populate_table_fixed,
    truncate,
)

PARTICIPANT_COLS = [
    ("agent", "Agent", None),
    ("persona", "Persona", None),
    ("model", "Model", 30),
    ("score", "Score", None),
    ("turns", "Turns", None),
]
SESSION_COLS = [
    ("id", "Session", None),
    ("topic", "Topic", 40),
    ("mode", "Mode", None),
    ("started", "Started", 16),
    ("verdict", "Synthesis (verdict)", 44),
]


class CommunityScreen(RaphaelScreen):
    TITLE = "raphael-ma · community"
    SHOWS_BRAIN_STRIP = True

    # ------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield StatusStrip(id="strip")
        with VerticalScroll(id="body"):
            with Horizontal(classes="form-row"):
                yield Label("topic")
                yield Input(placeholder="build vs buy a database", id="topic")
            with Horizontal(classes="form-row"):
                yield Label("agents (2–6)")
                yield Select([(str(n), n) for n in range(2, 7)], value=3, id="agents")
                yield Label("rounds")
                yield Input("1", id="rounds", type="integer")
                yield Label("quiet")
                yield Checkbox("", id="quiet")
                yield Label("stream")
                yield Checkbox("", id="stream", value=True)
            with Horizontal(classes="form-row"):
                yield Button("Run round-table", id="run", variant="warning")
                yield Button("pick models (F7)", id="pick-models")
                yield Button("past round-tables", id="toggle-sessions")
            yield Label("live round-table · specialist response matrix → moderator synthesis", classes="section-label")
            yield TurnEventPane(id="community-live", classes="run-pane")
            yield Label("moderator synthesis", classes="section-label")
            yield Static(
                "(run a round-table — the moderator's synthesis lands here)",
                id="community-synthesis",
                classes="synthesis-panel",
            )
            yield Static("", id="community-labels", classes="result-labels")
            yield Label("round-table contributions · scored by the moderator", classes="section-label")
            yield DataTable(id="community-participants", classes="mini-table")
            sessions = DataTable(id="community-sessions")
            sessions.display = False
            yield sessions
        output = OutputPane(id="output")
        output.display = False
        yield output
        yield CommandBar(id="cmdbar")
        yield ResultBanner(id="result")
        yield Footer()

    def on_mount(self) -> None:
        self._session_rows: List[Dict[str, Any]] = []
        self._session_modal: Optional[SessionDetailModal] = None
        self.call_after_refresh(self._load_sessions, True)

    # -------------------------------------------------------------- run
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "topic" and event.value.strip():
            self.query_one("#run", Button).press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "run":
            self._run()
        elif bid == "pick-models":
            self.app.action_screen("providers")
        elif bid == "toggle-sessions":
            table = self.query_one("#community-sessions", DataTable)
            table.display = not table.display
            if table.display and not table.row_count:
                self._load_sessions()

    def _run(self) -> None:
        topic = str(self._value("#topic") or "").strip()
        if not topic:
            self.app.notify("A community debate needs a topic.", title="Community", severity="warning")
            return
        agents = self._value("#agents") or 3
        rounds = str(self._value("#rounds") or "1").strip() or "1"
        argv = ["community", topic, "--agents", str(agents), "--rounds", rounds]
        argv += list(self.mode_flags())
        if self._value("#quiet"):
            argv.append("-q")
        argv.append("--stream" if self._value("#stream", default=True) else "--no-stream")
        pane = self.query_one("#community-live", TurnEventPane)
        pane.reset_stream()
        self.query_one("#community-synthesis", Static).update(
            "[dim]running the round-table — turns stream above…[/dim]"
        )
        self.run_command(
            argv,
            json_mode=True,
            pane=pane,
            label="community",
            on_done=self._on_done,
        )

    # ---------------------------------------------------------- results
    def _on_done(self, res: RunResult) -> None:
        synth_panel = self.query_one("#community-synthesis", Static)
        labels = self.query_one("#community-labels", Static)
        if not res.ok:
            synth_panel.update(
                f"[#f38ba8]✗ round-table failed — exit {res.code}[/]\n"
                f"[dim]{escape(next((ln for ln in res.err_lines if ln.strip()), '')[:160])}[/dim]"
            )
            labels.update("")
            return
        row: Dict[str, Any] = {}
        for candidate in parse_ndjson(res.out):
            if isinstance(candidate, dict) and "synthesis" in candidate:
                row = candidate
        if not row:
            synth_panel.update("[#f9e2af]? no synthesis in CLI output[/]")
            return
        body = escape(str(row.get("synthesis") or "(empty synthesis)"))
        sid = str(row.get("session_id") or "")
        if sid:
            body += f"\n\n[dim]session {escape(sid)} · recorded in the brain (F6 → Sessions)[/dim]"
        synth_panel.update(body)
        labels.update(self._labels_markup(row))
        participants = row.get("participants") or []
        populate_table_fixed(
            self.query_one("#community-participants", DataTable), participants, PARTICIPANT_COLS
        )
        # the new session is now the most recent one — quietly refresh history
        self._load_sessions(background=True)

    @staticmethod
    def _labels_markup(row: Dict[str, Any]) -> str:
        def section(marker: str, color: str, title: str, items: Sequence[Any]) -> str:
            if not items:
                return ""
            joined = escape("; ".join(truncate(i, 90) for i in items))
            return f"[{color}]{marker} {title}:[/{color}] {joined}"

        lines = [
            section("✓", "green", "consensus", row.get("consensus") or []),
            section("⚠", "amber", "dissent", row.get("dissent") or []),
            section("?", "cyan", "open questions", row.get("open_questions") or []),
        ]
        return "\n".join(ln for ln in lines if ln)

    # ------------------------------------------------------ session history
    def _load_sessions(self, background: bool = False) -> None:
        self.run_command(
            ["brain", "sessions", "--limit", "30"],
            json_mode=True,
            label="community history",
            background=background,
            on_done=self._fill_sessions,
        )

    def _fill_sessions(self, res: RunResult) -> None:
        if not res.ok:
            return
        rows = [r for r in parse_ndjson(res.out) if str(r.get("kind")) == "community"]
        self._session_rows = rows
        populate_table_fixed(
            self.query_one("#community-sessions", DataTable), rows, SESSION_COLS
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "community-sessions":
            return
        try:
            idx = int(event.row_key.value or -1)
        except (TypeError, ValueError):
            return
        rows = self._session_rows
        if idx < 0 or idx >= len(rows):
            return
        modal = SessionDetailModal(rows[idx], on_load_turns=self._load_session_turns)
        self._session_modal = modal
        self.app.push_screen(modal, callback=lambda _: self._forget_modal())

    def _forget_modal(self) -> None:
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
