"""Benchmark screen — run prompts across providers; table + ASCII bars."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Input, Label, Static

from raphael.multiagent.tui.widgets import ascii_bars, parse_ndjson, populate_table
from .base import RaphaelScreen


class BenchmarkScreen(RaphaelScreen):
    TITLE = "raphael-ma · benchmark"

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="form-row"):
            yield Label("prompt")
            yield Input(placeholder="test prompt", id="bench-prompt")
        with Horizontal(classes="form-row"):
            yield Label("providers")
            yield Input("mock", id="bench-providers")
            yield Label("rounds")
            yield Input("1", id="bench-rounds", type="integer")
        with Horizontal(classes="form-row"):
            yield Button("Run benchmark", id="btn-run", variant="warning")
            yield Button("benchmark providers", id="btn-providers")
        yield Label("results (NDJSON parsed schema-agnostically)", classes="section-label")
        yield DataTable(id="bench-table")
        yield Static("", id="bench-bars")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-providers":
            self.run_command(
                ["benchmark", "providers"],
                json_mode=True,
                label="benchmark providers",
                on_done=self._fill_table,
            )
        elif bid == "btn-run":
            prompt = self._value("#bench-prompt").strip()
            if not prompt:
                self.app.notify("Benchmark needs a prompt.", title="Benchmark", severity="warning")
                return
            providers = (self._value("#bench-providers") or "mock").strip() or "mock"
            rounds = (self._value("#bench-rounds") or "1").strip() or "1"
            argv = [
                "benchmark",
                "run",
                prompt,
                "-p",
                providers,
                "-r",
                rounds,
                "--json",
            ]
            argv += list(self.mode_flags())
            self.run_command(argv, json_mode=True, label="benchmark run", on_done=self._render_results)

    def _fill_table(self, res) -> None:
        populate_table(self.query_one("#bench-table", DataTable), parse_ndjson(res.out))

    def _render_results(self, res) -> None:
        rows = parse_ndjson(res.out)
        self._fill_table(res)
        bars = ascii_bars(rows)
        self.query_one("#bench-bars", Static).update(bars if bars else "(no numeric column found in NDJSON rows)")
