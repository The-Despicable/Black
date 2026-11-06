"""Provider status screen — list / test / models."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Label

from raphael.multiagent.tui.widgets import parse_ndjson, populate_table
from .base import RaphaelScreen


class ProvidersScreen(RaphaelScreen):
    TITLE = "raphael-ma · providers"

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="form-row"):
            yield Button("providers list", id="btn-list")
            yield Button("test selected", id="btn-test")
            yield Button("models of selected", id="btn-models")
        yield Label("select a provider row, then test it or list its models", classes="section-label")
        yield DataTable(id="providers-table")

    def on_mount(self) -> None:
        self._selected: str | None = None
        table = self.query_one("#providers-table", DataTable)
        table.cursor_type = "row"
        self.run_command(
            ["providers", "list"],
            json_mode=True,
            label="providers list",
            on_done=self._fill,
        )

    def _fill(self, res) -> None:
        populate_table(self.query_one("#providers-table", DataTable), parse_ndjson(res.out))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = self.query_one("#providers-table", DataTable)
        try:
            row = table.get_row(event.row_key)
        except Exception:
            return
        self._selected = str(row[0]) if row else None
        if self._selected:
            self.app.notify(f"selected provider: {self._selected}", title="Providers")

    def _require_selection(self) -> bool:
        if not getattr(self, "_selected", None):
            self.app.notify("Select a provider row first.", title="Providers", severity="warning")
            return False
        return True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-list":
            self.run_command(
                ["providers", "list"],
                json_mode=True,
                label="providers list",
                on_done=self._fill,
            )
        elif bid == "btn-test":
            if self._require_selection():
                self.run_command(["providers", "test", self._selected], label="providers test")
        elif bid == "btn-models":
            if self._require_selection():
                self.run_command(
                    ["providers", "models", self._selected],
                    json_mode=True,
                    label="providers models",
                )
