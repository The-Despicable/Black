"""Debate execution screen — PRO vs CON vs judge, streamed from the CLI."""

from __future__ import annotations

import re
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, Input, Label, Static

from raphael.multiagent.tui.screens.base import RaphaelScreen
from raphael.multiagent.tui.widgets import OutputPane


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
            yield Button("pick models (F7)", id="pick-models")
            yield Button("view transcript", id="view-transcript")
        yield Label("verdict is emitted by the CLI judge; insights link to outcomes automatically", classes="section-label")
        yield Label("roles consumed: pro · con · judge (bind live ids in Providers)", classes="section-label")
        yield Static("", id="verdict", classes="section-label")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pick-models":
            self.app.action_screen("providers")
            return
        if event.button.id == "view-transcript":
            self._view_transcript()
            return
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
        try:
            self.query_one("#verdict", Static).update("running debate…")
        except Exception:
            pass
        self.run_command(argv, label="debate", on_done=self._on_debate_done)

    def _on_debate_done(self, res) -> None:
        try:
            verdict = self.query_one("#verdict", Static)
        except Exception:
            return
        text = res.out or ""
        m = re.search(r"Winner:\s*([A-Za-z]+)", text)
        winner = (m.group(1).upper() if m else "—")
        tm = re.search(r"transcript\s*→\s*(.+)", text)
        transcript = tm.group(1).strip() if tm else ""
        score_m = re.search(r"PRO\s+[\d.]+\s*/\s*CON\s+[\d.]+", text)
        score_line = score_m.group(0) if score_m else ""
        lines = [f"Winner: {winner}"]
        if score_line:
            lines.append(score_line)
        if transcript:
            lines.append(f"Transcript: {transcript}")
        if not res.ok:
            lines.append(f"exit {res.code}: {(res.err_lines[0] if res.err_lines else '')[:80]}")
        verdict.update("\n".join(lines))

    def _view_transcript(self) -> None:
        pane = self.query_one("#output", OutputPane)
        pane.reset_stream()
        try:
            tdir = Path("transcripts")
            candidates = sorted(tdir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                self.app.notify("No transcripts found.", title="Debate", severity="warning")
                return
            latest = candidates[0]
            for line in latest.read_text(encoding="utf-8", errors="replace").splitlines():
                pane.write(line)
            self.app.notify(f"loaded {latest.name}", title="Transcript", timeout=3)
        except Exception as exc:
            self.app.notify(str(exc)[:120], title="Transcript", severity="error")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "motion" and event.value.strip():
            self.query_one("#run", Button).press()
