"""Debate execution screen — PRO vs CON vs judge.

v2: the debate runs in ``--json`` mode with every speech rendered live into
a dedicated pane (colored per-agent headers). The judge's verdict gets its
own panel — winner badge with a colored border (green PRO / red CON / amber
tie), scores and reasoning — and past debates can be reopened from the
history table (click a row for the session detail modal).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, Static

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
)

SESSION_COLS = [
    ("id", "Session", None),
    ("topic", "Motion", 44),
    ("mode", "Mode", None),
    ("started", "Started", 16),
    ("verdict", "Verdict", 44),
]


class DebateScreen(RaphaelScreen):
    TITLE = "raphael-ma · debate"
    SHOWS_BRAIN_STRIP = True

    # ------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield StatusStrip(id="strip")
        with VerticalScroll(id="body"):
            with Horizontal(classes="form-row"):
                yield Label("motion")
                yield Input(placeholder="AI will replace middle management", id="motion")
            with Horizontal(classes="form-row"):
                yield Label("rounds")
                yield Input("2", id="rounds", type="integer")
                yield Label("quiet")
                yield Checkbox("", id="quiet")
                yield Label("stream")
                yield Checkbox("", id="stream", value=True)
            with Horizontal(classes="form-row"):
                yield Button("Run debate", id="run", variant="warning")
                yield Button("pick models (F7)", id="pick-models")
                yield Button("past debates", id="toggle-sessions")
            yield Label(
                "live debate · verdict is emitted by the CLI judge; insights link to outcomes automatically",
                classes="section-label",
            )
            yield TurnEventPane(id="debate-live", classes="run-pane")
            yield Label("judge verdict", classes="section-label")
            yield Static("(run a debate — the judge's verdict lands here)", id="verdict", classes="verdict-panel tie")
            sessions = DataTable(id="debate-sessions")
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
        if event.input.id == "motion" and event.value.strip():
            self.query_one("#run", Button).press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "run":
            self._run()
        elif bid == "pick-models":
            self.app.action_screen("providers")
        elif bid == "toggle-sessions":
            table = self.query_one("#debate-sessions", DataTable)
            table.display = not table.display
            if table.display and not table.row_count:
                self._load_sessions()

    def _run(self) -> None:
        motion = str(self._value("#motion") or "").strip()
        if not motion:
            self.app.notify("A debate needs a motion.", title="Debate", severity="warning")
            return
        rounds = str(self._value("#rounds") or "2").strip() or "2"
        argv = ["debate", motion, "--rounds", rounds]
        argv += list(self.mode_flags())
        if self._value("#quiet"):
            argv.append("-q")
        argv.append("--stream" if self._value("#stream", default=True) else "--no-stream")
        pane = self.query_one("#debate-live", TurnEventPane)
        pane.reset_stream()
        self.query_one("#verdict", Static).update("[dim]debate running — speeches stream above…[/dim]")
        self.run_command(
            argv,
            json_mode=True,
            pane=pane,
            label="debate",
            on_done=self._on_debate_done,
        )

    # ---------------------------------------------------------- verdict
    def _on_debate_done(self, res: RunResult) -> None:
        panel = self.query_one("#verdict", Static)
        if not res.ok:
            panel.set_classes("verdict-panel loss")
            panel.update(
                f"[#f38ba8]✗ debate failed — exit {res.code}[/]\n"
                f"[dim]{escape(next((ln for ln in res.err_lines if ln.strip()), '')[:160])}[/dim]"
            )
            return
        row: Dict[str, Any] = {}
        for candidate in parse_ndjson(res.out):
            if isinstance(candidate, dict) and "winner" in candidate:
                row = candidate
        if not row:
            panel.set_classes("verdict-panel tie")
            panel.update("[#f9e2af]? no verdict in CLI output[/]")
            return
        winner = str(row.get("winner", "tie")).lower()
        scores = row.get("scores") or {}
        pro = scores.get("pro", "?")
        con = scores.get("con", "?")
        tone = "win" if winner == "pro" else ("loss" if winner == "con" else "tie")
        panel.set_classes(f"verdict-panel {tone}")
        badge = {"pro": "🏆 PRO", "con": "🏆 CON", "tie": "⚖ TIE"}.get(winner, winner.upper())
        lines = [
            f"[bold]Winner: {badge}[/bold]   [dim]PRO {escape(str(pro))} / CON {escape(str(con))}[/dim]",
        ]
        reasoning = str(row.get("reasoning") or "").strip()
        if reasoning:
            lines.append("")
            lines.append(escape(reasoning))
        sid = str(row.get("session_id") or "")
        if sid:
            lines.append("")
            lines.append(f"[dim]session {escape(sid)} · recorded in the brain (F6 → Sessions)[/dim]")
        panel.update("\n".join(lines))
        self._load_sessions(background=True)

    # ------------------------------------------------------ session history
    def _load_sessions(self, background: bool = False) -> None:
        self.run_command(
            ["brain", "sessions", "--limit", "30"],
            json_mode=True,
            label="debate history",
            background=background,
            on_done=self._fill_sessions,
        )

    def _fill_sessions(self, res: RunResult) -> None:
        if not res.ok:
            return
        rows = [r for r in parse_ndjson(res.out) if str(r.get("kind")) == "debate"]
        self._session_rows = rows
        populate_table_fixed(
            self.query_one("#debate-sessions", DataTable), rows, SESSION_COLS
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "debate-sessions":
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
