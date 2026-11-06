"""Governance & kill-switch screen — strictly read-only display.

Unrestricted governance is surfaced with a hard warning and can NOT be
enabled or normalized from this UI; that stays an explicit config/CLI
decision made outside the console.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Label, RichLog, Static

from raphael.multiagent.tui.widgets import tail_file
from .base import RaphaelScreen


class GovernanceScreen(RaphaelScreen):
    TITLE = "raphael-ma · governance"

    def compose_body(self) -> ComposeResult:
        yield Static("", id="gov-detail", classes="panel")
        yield Static("", id="unrestricted-warning", classes="panel danger")
        with Horizontal(classes="form-row"):
            yield Button("governance status", id="btn-gov-status")
            yield Button("refresh audit tail", id="btn-audit")
        yield Label("audit trail (JSONL, last 25 entries)", classes="section-label")
        yield RichLog(id="audit-tail", highlight=True, markup=False, wrap=True)
        yield Static(
            "\n".join(
                [
                    "notes",
                    "• kill-switch aborts surface as exit code 3 — sessions are marked aborted and audited",
                    "• governance config errors surface as exit code 4",
                    "• strict mode fails closed when governance is empty and no explicit override exists",
                    "• unrestricted mode audits but never blocks; it is never enabled from this UI",
                ]
            ),
            classes="panel",
        )

    def on_mount(self) -> None:
        self.refresh_governance()

    def on_show(self) -> None:
        self.refresh_governance()

    def refresh_on_show(self) -> None:
        self.refresh_governance()

    def refresh_governance(self) -> None:
        state = self.app.state
        state.load_config()
        detail = self.query_one("#gov-detail", Static)
        kill = state.kill_switch or "— empty (audit-only gate)"
        strict_note = "true — fail-closed" if state.strict else "false — standalone allow-mode"
        detail.update(
            "\n".join(
                [
                    "GOVERNANCE (from home/config.yaml)",
                    f"  type:        {state.governance_type}",
                    f"  kill switch: {kill}",
                    f"  strict:      {strict_note}",
                    f"  audit path:  {state.audit_path or '—'}",
                    f"  mode:        {state.config_mode or 'unset → mock'}",
                ]
            )
        )
        warning = self.query_one("#unrestricted-warning", Static)
        if state.unrestricted:
            warning.display = True
            warning.update(
                "\n".join(
                    [
                        "⚠ UNRESTRICTED GOVERNANCE ACTIVE",
                        "  audits but never blocks.",
                        "  appropriate ONLY for isolated, explicitly authorized testing.",
                        "  this UI refuses to enable or disable it — edit config/CLI deliberately.",
                    ]
                )
            )
        else:
            warning.display = False
            warning.update("")
        self.refresh_audit_tail()

    def refresh_audit_tail(self) -> None:
        state = self.app.state
        audit_rel = state.audit_path or "logs/harness_audit.jsonl"
        candidates = [Path(audit_rel), state.home_path / audit_rel]
        log_widget = self.query_one("#audit-tail", RichLog)
        log_widget.clear()
        for path in candidates:
            if path.exists():
                for line in tail_file(path, 25):
                    log_widget.write(line)
                return
        log_widget.write(f"audit log not found at {' or '.join(str(c) for c in candidates)}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-gov-status":
            self.run_command(["governance", "status"], label="governance status")
        elif event.button.id == "btn-audit":
            self.refresh_governance()
            self.app.notify("audit tail refreshed", title="Governance")
