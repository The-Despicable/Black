"""JSON / NDJSON inspection console — free-form argv against the real CLI.

``--json`` keeps stdout parseable (NDJSON tables) and sends status to stderr;
this screen shows both streams side by side plus the exit code, exactly as
the CLI contract defines.
"""

from __future__ import annotations

import shlex
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Footer, Input, Label, RichLog

from raphael.multiagent.tui.engine import RunResult
from raphael.multiagent.tui.widgets import CommandBar, ResultBanner, StatusStrip
from raphael.multiagent.tui.screens.base import RaphaelScreen

PRESETS = [
    ("brain status", "brain status"),
    ("brain sessions", "brain sessions --limit 10"),
    ("brain insights", "brain insights --active --limit 10"),
    ("brain log", "brain log --last 10"),
    ("evolve stats", "evolve stats"),
    ("benchmark providers", "benchmark providers"),
    ("doctor", "doctor"),
    ("config", "config"),
    ("version", "version"),
]

_PRESET_IDS = {f"preset-{i}": argv for i, (_, argv) in enumerate(PRESETS)}


class JsonConsoleScreen(RaphaelScreen):
    TITLE = "raphael-ma · JSON console"

    def compose(self) -> ComposeResult:
        yield StatusStrip(id="strip")
        with VerticalScroll(id="body"):
            with Horizontal(classes="form-row"):
                yield Label("argv")
                yield Input(placeholder="brain sessions --limit 5", id="free-args")
            with Horizontal(classes="form-row"):
                yield Checkbox("--json (NDJSON stdout / status stderr)", id="free-json", value=True)
                yield Checkbox("-v verbose", id="free-verbose")
                yield Button("Run", id="free-run", variant="warning")
            with Horizontal(classes="form-row"):
                for i, (label, _argv) in enumerate(PRESETS):
                    yield Button(label, id=f"preset-{i}")
            with Horizontal(id="split"):
                with Vertical(id="out-col"):
                    yield Label("stdout — NDJSON tables")
                    yield RichLog(id="out-log", highlight=True, markup=False, wrap=True)
                with Vertical(id="err-col"):
                    yield Label("stderr — status")
                    yield RichLog(id="err-log", highlight=True, markup=False, wrap=True)
        yield CommandBar(id="cmdbar")
        yield ResultBanner(id="result")
        yield Footer()

    # ------------------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "free-run":
            self._run_free()
        elif bid in _PRESET_IDS:
            self.query_one("#free-args", Input).value = _PRESET_IDS[bid]
            self._run_free()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "free-args":
            self._run_free()

    def _run_free(self) -> None:
        app = self.app
        state = app.state
        if state.busy:
            app.notify("A command is already running — wait for it to finish.", title="Busy", severity="warning")
            return
        raw = self._value("#free-args").strip()
        if not raw:
            app.notify("Type an argv, e.g. 'brain sessions --limit 5'.", title="JSON console", severity="warning")
            return
        try:
            argv = shlex.split(raw)
        except ValueError as exc:
            app.notify(f"Cannot parse argv: {exc}", title="JSON console", severity="error")
            return
        json_mode = self._value("#free-json", default=True)
        full = state.augment(argv, json_mode=bool(json_mode))
        out_log = self.query_one("#out-log", RichLog)
        err_log = self.query_one("#err-log", RichLog)
        out_log.clear()
        err_log.clear()
        self.query_one("#cmdbar", CommandBar).set_argv(full)
        banner = self.query_one("#result", ResultBanner)
        banner.set_running(full, "free-form")
        state.busy = True
        engine = app.engine

        def work() -> None:
            res = engine.run(full)

            def done() -> None:
                for line in res.out_lines:
                    out_log.write(line)
                for line in res.err_lines:
                    err_log.write(line)
                banner.set_result(res)
                state.busy = False
                state.last_result = res
                self._notify_result(app, res)

            try:
                app.call_from_thread(done)
            except Exception:
                pass

        self.run_worker(work, thread=True, group="cmd", name="free-form")
