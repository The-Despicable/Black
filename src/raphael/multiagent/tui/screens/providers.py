"""Provider status screen — list / test / models / live model selection."""

from __future__ import annotations

from typing import Dict, List

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Input, Label, OptionList

from raphael.multiagent.tui.widgets import latest_models_row, parse_ndjson, populate_table
from raphael.multiagent.tui.screens.base import RaphaelScreen


class ProvidersScreen(RaphaelScreen):
    TITLE = "raphael-ma · providers"

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="form-row"):
            yield Button("providers list", id="btn-list")
            yield Button("test selected", id="btn-test")
            yield Button("live models", id="btn-models")
        yield Label(
            "focus: nvidia · ollama-cloud · inferx (the 3 key'd providers)",
            classes="section-label",
        )
        yield DataTable(id="providers-table")
        model_list = OptionList(id="model-list")
        model_list.styles.height = 12
        model_list.display = False
        yield model_list
        with Horizontal(classes="form-row"):
            yield Label("model")
            yield Input(
                placeholder="pick from list, or type an id",
                id="model-id",
            )
            yield Label("role")
            yield Input("chat", id="role")
            yield Button("bind model", id="btn-bind", variant="primary")
        yield Label(
            "select a row, fetch its live /models list, click a model, bind it to a role",
            classes="section-label",
        )

    def on_mount(self) -> None:
        self._selected: str | None = None
        self._live_models: List[str] = []
        table = self.query_one("#providers-table", DataTable)
        table.cursor_type = "row"
        self.run_command(
            ["providers", "list"],
            json_mode=True,
            label="providers list",
            on_done=self._fill,
        )

    def _fill(self, res) -> None:
        # focus the table on enabled, keyed providers (the ones the picker
        # can actually fetch live lists / bind models for)
        rows = [r for r in parse_ndjson(res.out) if str(r.get("enabled", "yes")).lower() in ("yes", "true")]
        populate_table(self.query_one("#providers-table", DataTable), rows)

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

    # ------------------------------------------------------------------
    def _load_models(self) -> None:
        if not self._require_selection():
            return
        self.run_command(
            ["providers", "models", self._selected],
            json_mode=True,
            label="live models",
            on_done=self._fill_models,
        )

    def _fill_models(self, res) -> None:
        row = latest_models_row(res)
        if not row:
            self.app.notify("No live model list returned.", title="Providers", severity="warning")
            return
        self._live_models = [str(m) for m in row["models"]]
        picker = self.query_one("#model-list", OptionList)
        picker.clear_options()
        picker.add_options(self._live_models)
        picker.display = True
        self.app.notify(
            f"{row.get('provider', self._selected)}: {len(self._live_models)} live models — click one to fill the input",
            title="Providers",
        )

    def _bind(self) -> None:
        if not self._require_selection():
            return
        model_id = self._value("#model-id").strip()
        role = (self._value("#role").strip() or "chat").strip()
        if not model_id:
            self.app.notify(
                "Type a model id (or fetch live models and click one) first.",
                title="Providers",
                severity="warning",
            )
            return
        self.run_command(
            ["providers", "select", self._selected, "--model", model_id, "--role", role],
            json_mode=True,
            label="bind model",
            on_done=self._after_bind,
        )

    def _after_bind(self, res) -> None:
        if res.ok:
            self.run_command(
                ["providers", "list"],
                json_mode=True,
                label="providers list",
                on_done=self._fill,
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        try:
            choice = str(self._live_models[event.option_index])
        except Exception:
            return
        self.query_one("#model-id", Input).value = choice

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
            self._load_models()
        elif bid == "btn-bind":
            self._bind()
