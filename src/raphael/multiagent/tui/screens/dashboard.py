"""Dashboard: mode arming, home state, engine import status, quick actions."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Checkbox, DataTable, Label, Static

from raphael.multiagent.tui.widgets import parse_ndjson, populate_table, tail_file
from raphael.multiagent.tui.screens.base import RaphaelScreen


class DashboardScreen(RaphaelScreen):
    TITLE = "raphael-ma · dashboard"

    def compose_body(self) -> ComposeResult:
        with Horizontal(id="dash-panels"):
            yield Static("", id="mode-panel", classes="panel")
            yield Static("", id="home-panel", classes="panel")
            yield Static("", id="engine-panel", classes="panel")
            yield Static("", id="gov-panel", classes="panel")
        with Horizontal(id="dash-actions"):
            yield Button("Arm LIVE / Disarm (F2)", id="btn-mode")
            yield Button("Initialize (init)", id="btn-init")
            yield Button("Doctor", id="btn-doctor")
            yield Button("Config", id="btn-config")
            yield Button("Version", id="btn-version")
            yield Button("Evolve stats", id="btn-evolve")
            yield Checkbox("verbose (-v)", id="chk-verbose")
        yield Label("recent sessions  (raphael-ma --json brain sessions --limit 5)", classes="section-label")
        yield DataTable(id="recent-sessions")

    def on_mount(self) -> None:
        self.refresh_dashboard()
        self.call_after_refresh(self._auto_load_sessions)

    def on_show(self) -> None:
        self.refresh_dashboard()

    def refresh_on_show(self) -> None:
        self.refresh_dashboard()

    # ------------------------------------------------------------------
    def refresh_dashboard(self) -> None:
        state = self.app.state
        self.query_one("#chk-verbose", Checkbox).value = state.verbose

        # mode panel ------------------------------------------------------
        armed = "LIVE · ARMED (--live)" if state.armed_live else "MOCK (--mock, explicit)"
        config_mode = state.config_mode or "unset → mock"
        live_note = (
            "commands run against real providers"
            if state.armed_live
            else "safe: never auto-runs live"
        )
        self.query_one("#mode-panel", Static).update(
            "\n".join(
                [
                    "MODE",
                    f"  armed:    {armed}",
                    f"  config:   {config_mode}",
                    f"  behavior: {live_note}",
                    "  toggle:   F2 / button below",
                ]
            )
        )

        # home panel ------------------------------------------------------
        home = state.home_path
        db = state.db_path
        db_note = "✗ missing"
        if db.exists():
            try:
                db_note = f"✓ {db.stat().st_size / 1024:.1f} KB"
            except Exception:
                db_note = "✓ present"
            wal = Path(str(db) + "-wal")
            db_note += "  WAL:" + ("✓" if wal.exists() else "—")
        transcripts = sorted(Path("transcripts").glob("*.md")) if Path("transcripts").exists() else []
        audit = state.audit_path or "logs/harness_audit.jsonl"
        audit_path = Path(audit)
        if not audit_path.exists():
            audit_path = home / audit
        audit_note = "✓ " + str(len(tail_file(audit_path, 10_000))) + " lines" if audit_path.exists() else "✗ not found"
        self.query_one("#home-panel", Static).update(
            "\n".join(
                [
                    "HOME",
                    f"  path:         {home}",
                    f"  config.yaml:  {'✓' if state.config_path.exists() else '✗ — run init'}",
                    f"  brain.db:     {db_note}",
                    f"  transcripts:  {len(transcripts)} (./transcripts)",
                    f"  audit log:    {audit_note}",
                ]
            )
        )

        # engine panel ----------------------------------------------------
        if state.engine_ok is None:
            engine = "  import:  probing…"
        elif state.engine_ok:
            engine = f"  import:  ✓ {state.engine_path}"
        else:
            engine = "  import:  ✗ not importable"
            if state.engine_error:
                engine += f"\n           {state.engine_error[:80]}"
        self.query_one("#engine-panel", Static).update(
            "\n".join(
                [
                    "ENGINE",
                    engine,
                    "  exec:    in-process Typer command surface",
                    "  mode:    get_command(raphael-ma).main()",
                ]
            )
        )

        # governance panel ------------------------------------------------
        gov_panel = self.query_one("#gov-panel", Static)
        if state.unrestricted:
            gov_panel.set_classes("panel danger")
            gov_panel.update(
                "\n".join(
                    [
                        "GOVERNANCE — UNRESTRICTED",
                        "  audits but NEVER blocks.",
                        "  authorized isolated testing only.",
                        "  cannot be enabled from this UI.",
                    ]
                )
            )
        else:
            gov_panel.set_classes("panel")
            kill = state.kill_switch or "— empty"
            strict_note = "on (fail-closed)" if state.strict else "off (standalone allow-mode)"
            gov_panel.update(
                "\n".join(
                    [
                        "GOVERNANCE",
                        f"  type:        {state.governance_type}",
                        f"  kill switch: {kill}",
                        f"  strict:      {strict_note}",
                        f"  audit:       {state.audit_path or '—'}",
                    ]
                )
            )

    # ------------------------------------------------------------------
    def _auto_load_sessions(self) -> None:
        if self.app.state.busy:
            return
        self.run_command(
            ["brain", "sessions", "--limit", "5"],
            json_mode=True,
            label="auto status",
            on_done=self._fill_sessions,
        )

    def _fill_sessions(self, res) -> None:
        table = self.query_one("#recent-sessions", DataTable)
        populate_table(table, parse_ndjson(res.out))
        self.refresh_dashboard()

    # ------------------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        state = self.app.state
        bid = event.button.id
        if bid == "btn-mode":
            self.app.action_toggle_mode()
            self.refresh_dashboard()
        elif bid == "btn-init":
            self.run_command(["init"], label="init")
        elif bid == "btn-doctor":
            self.run_command(["doctor"], label="doctor")
        elif bid == "btn-config":
            self.run_command(["config"], label="config")
        elif bid == "btn-version":
            self.run_command(["version"], label="version")
        elif bid == "btn-evolve":
            self.run_command(["evolve", "stats"], json_mode=True, label="evolve stats")
        if bid in {"btn-init", "btn-doctor", "btn-config", "btn-version", "btn-evolve"}:
            state.load_config()
            self.call_after_refresh(self.refresh_dashboard)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "chk-verbose":
            self.app.state.verbose = event.value
            self.app.notify(f"verbose {'on' if event.value else 'off'} — runs add -v / RAPHAEL_MA_LOG=debug", title="Verbose")
