"""Team workspace screen — YAML team plans, parallel execution, deliverables.

v2: the plan file is previewed before running (teams, members, personas,
providers/models, lead flags, mission — parsed straight from the YAML), the
run streams every agent turn live into a dedicated pane, and the final
deliverable + per-team summary render inline when the integrator finishes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

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

try:  # yaml is a core dependency of the project (teams plans)
    import yaml
except Exception:  # pragma: no cover — defensive only
    yaml = None  # type: ignore[assignment]

PLAN_MEMBER_COLS = [
    ("team", "Team", None),
    ("member", "Member", None),
    ("persona", "Persona", None),
    ("provider", "Provider", 14),
    ("model", "Model", 30),
    ("lead", "Lead", None),
]
TEAM_RESULT_COLS = [
    ("team", "Team", None),
    ("task", "Task", 36),
    ("members", "Members", 28),
    ("result", "Result", 48),
]
SESSION_COLS = [
    ("id", "Session", None),
    ("topic", "Mission", 40),
    ("mode", "Mode", None),
    ("started", "Started", 16),
]


class TeamsScreen(RaphaelScreen):
    TITLE = "raphael-ma · team workspace"
    SHOWS_BRAIN_STRIP = True

    # ------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield StatusStrip(id="strip")
        with VerticalScroll(id="body"):
            with Horizontal(classes="form-row"):
                yield Label("team plan (YAML)")
                yield Input("examples/teams.example.yaml", id="plan")
                yield Button("preview plan", id="preview", variant="primary")
            with Horizontal(classes="form-row"):
                yield Label("mission")
                yield Input(placeholder="optional --mission override", id="mission")
            with Horizontal(classes="form-row"):
                yield Label("integration")
                yield Select([("report", "report"), ("debate", "debate")], value="report", id="integration")
                yield Label("parallel")
                yield Checkbox("", id="parallel", value=True)
                yield Label("quiet")
                yield Checkbox("", id="quiet")
                yield Label("stream")
                yield Checkbox("", id="stream", value=True)
            with Horizontal(classes="form-row"):
                yield Button("Run team plan", id="run", variant="warning")
                yield Button("pick models (F7)", id="pick-models")
                yield Button("past missions", id="toggle-sessions")
            yield Static("(preview or run a plan — team roster shows here)", id="plan-meta", classes="plan-meta")
            yield DataTable(id="plan-teams", classes="mini-table")
            yield Label("live mission · intra-team collaboration → integration → deliverable", classes="section-label")
            yield TurnEventPane(id="teams-live", classes="run-pane")
            yield Label("integrator deliverable", classes="section-label")
            yield Static("(the integrator's final deliverable lands here)", id="teams-result", classes="synthesis-panel")
            yield DataTable(id="teams-table", classes="mini-table")
            sessions = DataTable(id="teams-sessions")
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

    # ------------------------------------------------------ plan preview
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "mission" and str(event.value).strip():
            self.query_one("#run", Button).press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "preview":
            self._preview_plan()
        elif bid == "run":
            self._run()
        elif bid == "pick-models":
            self.app.action_screen("providers")
        elif bid == "toggle-sessions":
            table = self.query_one("#teams-sessions", DataTable)
            table.display = not table.display
            if table.display and not table.row_count:
                self._load_sessions()

    def _plan_path(self) -> Optional[Path]:
        raw = str(self._value("#plan") or "").strip()
        if not raw:
            self.app.notify("A team plan path is required (teams.yaml).", title="Teams", severity="warning")
            return None
        path = Path(raw).expanduser()
        if not path.exists():
            self.app.notify(
                f"{raw} does not exist relative to the current working directory.",
                title="Teams",
                severity="warning",
            )
            return None
        return path

    def _preview_plan(self) -> None:
        path = self._plan_path()
        if path is None or yaml is None:
            if yaml is None:
                self.app.notify("PyYAML is not installed — cannot preview plans.", title="Teams", severity="error")
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            self.app.notify(f"cannot parse {path.name}: {exc}", title="Teams", severity="error")
            return
        if not isinstance(data, dict) or not data.get("teams"):
            self.app.notify(
                f"{path.name} has no 'teams:' mapping — see examples/teams.example.yaml.",
                title="Teams", severity="warning",
            )
            return
        rows: List[Dict[str, Any]] = []
        n_members = 0
        for name, spec in (data.get("teams") or {}).items():
            spec = spec or {}
            for m in spec.get("members") or []:
                n_members += 1
                rows.append({
                    "team": str(name),
                    "member": str(m.get("name", "?")),
                    "persona": str(m.get("persona", "—")),
                    "provider": str(m.get("provider", "(default)")),
                    "model": str(m.get("model", "(role default)")),
                    "lead": bool(m.get("lead", False)),
                })
        integration = (data.get("integration") or {}).get("mode", "report")
        mission = str(data.get("mission") or "(no mission statement)")
        self.query_one("#plan-meta", Static).update(
            f"📄 {escape(path.name)} · {len(data['teams'])} team(s) · "
            f"{n_members} member(s) · integration {escape(str(integration))}\n"
            f"mission: {escape(truncate(mission, 100))}"
        )
        populate_table_fixed(self.query_one("#plan-teams", DataTable), rows, PLAN_MEMBER_COLS)
        self.app.notify(
            f"plan ok — {len(data['teams'])} team(s), {n_members} member(s); "
            "provider/model gaps fall back to role defaults at run time",
            title="Teams", timeout=5,
        )

    # -------------------------------------------------------------- run
    def _run(self) -> None:
        path = self._plan_path()
        if path is None:
            return
        mission = str(self._value("#mission") or "").strip()
        integration = self._value("#integration") or "report"
        argv = ["teams", str(path), "--integration", str(integration)]
        if mission:
            argv += ["--mission", mission]
        if self._value("#parallel", default=True):
            argv.append("--parallel")
        argv += list(self.mode_flags())
        if self._value("#quiet"):
            argv.append("-q")
        argv.append("--stream" if self._value("#stream", default=True) else "--no-stream")
        pane = self.query_one("#teams-live", TurnEventPane)
        pane.reset_stream()
        self.query_one("#teams-result", Static).update(
            "[dim]mission running — team turns stream above…[/dim]"
        )
        self.run_command(
            argv,
            json_mode=True,
            pane=pane,
            label="teams",
            on_done=self._on_done,
        )

    def _on_done(self, res: RunResult) -> None:
        panel = self.query_one("#teams-result", Static)
        if not res.ok:
            panel.update(
                f"[#f38ba8]✗ mission failed — exit {res.code}[/]\n"
                f"[dim]{escape(next((ln for ln in res.err_lines if ln.strip()), '')[:160])}[/dim]"
            )
            return
        row: Dict[str, Any] = {}
        for candidate in parse_ndjson(res.out):
            if isinstance(candidate, dict) and "deliverable" in candidate:
                row = candidate
        if not row:
            panel.update("[#f9e2af]? no deliverable in CLI output[/]")
            return
        body = escape(str(row.get("deliverable") or "(empty)"))
        sid = str(row.get("session_id") or "")
        if sid:
            body += f"\n\n[dim]session {escape(sid)} · recorded in the brain (F6 → Sessions)[/dim]"
        panel.update(body)
        teams = row.get("teams") or []
        rows = []
        for t in teams:
            rows.append({
                "team": t.get("team"),
                "task": truncate(t.get("task"), 60),
                "members": ", ".join(str(m) for m in (t.get("members") or [])),
                "result": truncate(t.get("result"), 90),
            })
        populate_table_fixed(self.query_one("#teams-table", DataTable), rows, TEAM_RESULT_COLS)
        self._load_sessions(background=True)

    # ------------------------------------------------------ session history
    def _load_sessions(self, background: bool = False) -> None:
        self.run_command(
            ["brain", "sessions", "--limit", "30"],
            json_mode=True,
            label="teams history",
            background=background,
            on_done=self._fill_sessions,
        )

    def _fill_sessions(self, res: RunResult) -> None:
        if not res.ok:
            return
        rows = [r for r in parse_ndjson(res.out) if str(r.get("kind")) == "teams"]
        self._session_rows = rows
        populate_table_fixed(
            self.query_one("#teams-sessions", DataTable), rows, SESSION_COLS
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "teams-sessions":
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
