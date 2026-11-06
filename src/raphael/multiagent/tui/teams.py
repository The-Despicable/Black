"""Team workspace screen — YAML team plans, parallel execution, deliverables."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, Input, Label, Select

from .base import RaphaelScreen


class TeamsScreen(RaphaelScreen):
    TITLE = "raphael-ma · team workspace"

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="form-row"):
            yield Label("team plan (YAML)")
            yield Input("examples/teams.example.yaml", id="plan")
        with Horizontal(classes="form-row"):
            yield Label("mission")
            yield Input(placeholder="optional --mission override", id="mission")
        with Horizontal(classes="form-row"):
            yield Label("integration")
            yield Select(
                [("report", "report"), ("debate", "debate")],
                value="report",
                id="integration",
            )
            yield Label("parallel")
            yield Checkbox("", id="parallel", value=True)
        with Horizontal(classes="form-row"):
            yield Label("quiet")
            yield Checkbox("", id="quiet")
            yield Label("stream")
            yield Checkbox("", id="stream", value=True)
        with Horizontal(classes="form-row"):
            yield Button("Run team plan", id="run", variant="warning")
        yield Label(
            "intra-team collaboration → integration mode (report/debate) → integrator deliverable + transcript",
            classes="section-label",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "run":
            return
        plan = self._value("#plan").strip()
        if not plan:
            self.app.notify("A team plan path is required (teams.yaml).", title="Teams", severity="warning")
            return
        if not Path(plan).exists():
            self.app.notify(
                f"{plan} does not exist relative to the current working directory — the CLI "
                "will fail unless the path resolves.",
                title="Teams",
                severity="warning",
            )
        mission = self._value("#mission").strip()
        integration = self._value("#integration") or "report"
        argv = ["teams", plan, "--integration", str(integration)]
        if mission:
            argv += ["--mission", mission]
        if self._value("#parallel", default=True):
            argv.append("--parallel")
        argv += list(self.mode_flags())
        if self._value("#quiet"):
            argv.append("-q")
        argv.append("--stream" if self._value("#stream", default=True) else "--no-stream")
        self.run_command(argv, label="teams")
