"""Community debate screen — specialists, moderator synthesis, scoring."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, Input, Label, Select

from raphael.multiagent.tui.screens.base import RaphaelScreen


class CommunityScreen(RaphaelScreen):
    TITLE = "raphael-ma · community"

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="form-row"):
            yield Label("topic")
            yield Input(placeholder="build vs buy a database", id="topic")
        with Horizontal(classes="form-row"):
            yield Label("agents (2–6)")
            yield Select(
                [(str(n), n) for n in range(2, 7)],
                value=3,
                id="agents",
            )
            yield Label("rounds")
            yield Input("1", id="rounds", type="integer")
        with Horizontal(classes="form-row"):
            yield Label("quiet")
            yield Checkbox("", id="quiet")
            yield Label("stream")
            yield Checkbox("", id="stream", value=True)
        with Horizontal(classes="form-row"):
            yield Button("Run community debate", id="run", variant="warning")
            yield Button("pick models (F7)", id="pick-models")
        yield Label(
            "specialist response matrix → moderator synthesis → consensus / dissent / open questions",
            classes="section-label",
        )
        yield Label("roles consumed: analyst · moderator (bind live ids in Providers)", classes="section-label")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "run":
            return
        topic = self._value("#topic").strip()
        if not topic:
            self.app.notify("A community debate needs a topic.", title="Community", severity="warning")
            return
        agents = self._value("#agents") or 3
        rounds = (self._value("#rounds") or "1").strip() or "1"
        argv = ["community", topic, "--agents", str(agents), "--rounds", rounds]
        argv += list(self.mode_flags())
        if self._value("#quiet"):
            argv.append("-q")
        argv.append("--stream" if self._value("#stream", default=True) else "--no-stream")
        self.run_command(argv, label="community")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pick-models":
            self.app.action_screen("providers")
