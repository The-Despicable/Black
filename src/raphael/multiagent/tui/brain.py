"""Brain screen — status, insights, search, log, sessions, evolve, danger zone."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, Input, Label, Select, TabbedContent, TabPane

from raphael.multiagent.tui.widgets import parse_ndjson
from .base import ConfirmModal, RaphaelScreen


class BrainScreen(RaphaelScreen):
    TITLE = "raphael-ma · brain"

    def compose_body(self) -> ComposeResult:
        with TabbedContent(id="brain-tabs"):
            with TabPane("Status", id="pane-status"):
                with Horizontal(classes="form-row"):
                    yield Button("brain status", id="btn-status")
            with TabPane("Insights", id="pane-insights"):
                with Horizontal(classes="form-row"):
                    yield Label("scope")
                    yield Select([("active", "active"), ("all", "all")], value="active", id="ins-scope")
                    yield Label("limit")
                    yield Input("10", id="ins-limit", type="integer")
                    yield Button("Load insights", id="btn-insights")
            with TabPane("Search", id="pane-search"):
                with Horizontal(classes="form-row"):
                    yield Label("query")
                    yield Input(placeholder="vector recall query", id="srch-query")
                with Horizontal(classes="form-row"):
                    yield Label("top-k")
                    yield Input("5", id="srch-k", type="integer")
                    yield Button("Search", id="btn-search")
            with TabPane("Log", id="pane-log"):
                with Horizontal(classes="form-row"):
                    yield Label("last")
                    yield Input("20", id="log-last", type="integer")
                    yield Label("offset")
                    yield Input("0", id="log-offset", type="integer")
                with Horizontal(classes="form-row"):
                    yield Label("session")
                    yield Input(placeholder="session id (optional)", id="log-session")
                    yield Button("Load log", id="btn-log")
            with TabPane("Sessions", id="pane-sessions"):
                with Horizontal(classes="form-row"):
                    yield Label("limit")
                    yield Input("20", id="sess-limit", type="integer")
                    yield Label("offset")
                    yield Input("0", id="sess-offset", type="integer")
                    yield Button("Load sessions", id="btn-sessions")
            with TabPane("Evolve", id="pane-evolve"):
                with Horizontal(classes="form-row"):
                    yield Button("evolve stats", id="btn-evolve-stats")
                    yield Button("evolve evaluate", id="btn-evolve-evaluate")
                with Horizontal(classes="form-row"):
                    yield Label("dry-run")
                    yield Checkbox("", id="evolve-dry", value=True)
                    yield Button("evolve run", id="btn-evolve-run", variant="warning")
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
        yield Label(
            "NDJSON rows are parsed schema-agnostically — the real CLI output is the truth",
            classes="section-label",
        )

    def on_mount(self) -> None:
        self.run_command(["brain", "status"], label="brain status")

    # ------------------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-status":
            self.run_command(["brain", "status"], label="brain status")
        elif bid == "btn-insights":
            scope = self._value("#ins-scope") or "active"
            limit = (self._value("#ins-limit") or "10").strip() or "10"
            argv = ["brain", "insights", "--limit", limit]
            argv.append("--all" if scope == "all" else "--active")
            self.run_command(argv, json_mode=True, label="brain insights")
        elif bid == "btn-search":
            query = self._value("#srch-query").strip()
            if not query:
                self.app.notify("Search needs a query.", title="Brain", severity="warning")
                return
            k = (self._value("#srch-k") or "5").strip() or "5"
            self.run_command(
                ["brain", "search", query, "-k", k],
                json_mode=True,
                label="brain search",
            )
        elif bid == "btn-log":
            last = (self._value("#log-last") or "20").strip() or "20"
            argv = ["brain", "log", "--last", last]
            offset = (self._value("#log-offset") or "0").strip()
            if offset and offset != "0":
                argv += ["--offset", offset]
            session = self._value("#log-session").strip()
            if session:
                argv += ["--session", session]
            self.run_command(argv, json_mode=True, label="brain log")
        elif bid == "btn-sessions":
            limit = (self._value("#sess-limit") or "20").strip() or "20"
            argv = ["brain", "sessions", "--limit", limit]
            offset = (self._value("#sess-offset") or "0").strip()
            if offset and offset != "0":
                argv += ["--offset", offset]
            self.run_command(argv, json_mode=True, label="brain sessions")
        elif bid == "btn-evolve-stats":
            self.run_command(["evolve", "stats"], json_mode=True, label="evolve stats")
        elif bid == "btn-evolve-evaluate":
            self.run_command(["evolve", "evaluate"], json_mode=True, label="evolve evaluate")
        elif bid == "btn-evolve-run":
            argv = ["evolve", "run"]
            if self._value("#evolve-dry", default=True):
                argv.append("--dry-run")
            argv += list(self.mode_flags())
            self.run_command(argv, json_mode=True, label="evolve run")
        elif bid == "btn-rollback":
            evolution_id = self._value("#rb-id").strip()
            if not evolution_id:
                self.app.notify("Rollback needs an evolution id.", title="Brain", severity="warning")
                return
            self.app.push_screen(
                ConfirmModal(
                    f"Roll back evolution {evolution_id}?\nPersona/strategy changes are reverted "
                    "and the rollback is propagated — this cannot be undone from here."
                ),
                callback=lambda ok: self._rollback(ok, evolution_id),
            )
        elif bid == "btn-reset":
            self.app.push_screen(
                ConfirmModal(
                    "Reset the brain?\nThis wipes the SQLite brain (sessions, turns, insights, "
                    "outcomes, evolutions). Persona genomes return to seed v1."
                ),
                callback=self._reset,
            )
        elif bid == "btn-import":
            path = self._value("#imp-path").strip()
            if not path:
                self.app.notify("Import needs a session.json path.", title="Brain", severity="warning")
                return
            argv = ["brain", "import", path]
            sid = self._value("#imp-sid").strip()
            if sid:
                argv += ["--session-id", sid]
            self.run_command(argv, label="brain import")

    def _rollback(self, ok: bool, evolution_id: str) -> None:
        if ok:
            self.run_command(["brain", "rollback", evolution_id], label="brain rollback")

    def _reset(self, ok: bool) -> None:
        if ok:
            self.run_command(["brain", "reset", "--yes"], label="brain reset")
