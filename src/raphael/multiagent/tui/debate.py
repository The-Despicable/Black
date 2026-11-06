"""Debate execution screen — PRO vs CON vs judge, streamed from the CLI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, Input, Label

from .base import RaphaelScreen


class DebateScreen(RaphaelScreen):
    TITLE = "raphael-ma · debate"

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="form-row"):
            yield Label("motion")
            yield Input(
                placeholder="AI will replace middle management",
                id="motion",
            )
        with Horizontal(classes="form-row"):
            yield Label("rounds")
            yield Input("2", id="rounds", type="integer")
            yield Label("quiet")
            yield Checkbox("", id="quiet")
            yield Label("stream")
            yield Checkbox("", id="stream", value=True)
        with Horizontal(classes="form-row"):
            yield Button("Run debate", id="run", variant="warning")
        yield Label("verdict is emitted by the CLI judge; insights link to outcomes automatically", classes="section-label")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "run":
            return
        motion = self._value("#motion").strip()
        if not motion:
            self.app.notify("A debate needs a motion.", title="Debate", severity="warning")
            return
        rounds = (self._value("#rounds") or "2").strip() or "2"
        argv = ["debate", motion, "--rounds", rounds]
        argv += list(self.mode_flags())
        if self._value("#quiet"):
            argv.append("-q")
        argv.append("--stream" if self._value("#stream", default=True) else "--no-stream")
        self.run_command(argv, label="debate")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "motion" and event.value.strip():
            self.query_one("#run", Button).press()
