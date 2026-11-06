"""Audit / session transcript viewer — markdown transcripts, session JSON, audit log."""

from __future__ import annotations

from pathlib import Path
from typing import List

from rich.markdown import Markdown
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, ListItem, ListView, Static

from raphael.multiagent.tui.widgets import tail_file
from .base import RaphaelScreen


class TranscriptScreen(RaphaelScreen):
    TITLE = "raphael-ma · transcripts"

    MODES = ("transcripts", "sessions", "audit")

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="form-row"):
            yield Button("transcripts (*.md)", id="btn-md")
            yield Button("session exports (*.json)", id="btn-json")
            yield Button("audit log", id="btn-audit")
        with Horizontal(id="doc-split"):
            yield ListView(id="files-list")
            with VerticalScroll(id="doc-scroll"):
                yield Static("select a file to view it", id="doc-view")

    def on_mount(self) -> None:
        self._mode = "transcripts"
        self.refresh_list()

    def on_show(self) -> None:
        self.refresh_list()

    def refresh_on_show(self) -> None:
        self.refresh_list()

    # ------------------------------------------------------------------
    def _sources(self) -> List[Path]:
        state = self.app.state
        if self._mode == "transcripts":
            paths: List[Path] = []
            for base in (Path("transcripts"), state.home_path / "transcripts"):
                if base.exists():
                    paths.extend(sorted(base.glob("*.md")))
            seen = set()
            unique = []
            for p in paths:
                if p.name not in seen:
                    seen.add(p.name)
                    unique.append(p)
            return unique
        if self._mode == "sessions":
            paths = []
            for base in (Path("transcripts"), Path("sessions"), state.home_path):
                if base.exists():
                    paths.extend(sorted(base.glob("*.json")))
            return paths
        audit_rel = state.audit_path or "logs/harness_audit.jsonl"
        return [p for p in (Path(audit_rel), state.home_path / audit_rel) if p.exists()]

    def refresh_list(self) -> None:
        files = self._sources()
        list_view = self.query_one("#files-list", ListView)
        list_view.clear()
        for path in files:
            list_view.append(ListItem(Label(f"{path.name}  ({path.parent})")))
        self._files = files
        view = self.query_one("#doc-view", Static)
        if not files:
            view.update(f"no files for mode '{self._mode}' — run a session first")

    # ------------------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-md":
            self._mode = "transcripts"
        elif bid == "btn-json":
            self._mode = "sessions"
        elif bid == "btn-audit":
            self._mode = "audit"
        else:
            return
        self.refresh_list()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        files = getattr(self, "_files", [])
        list_view = self.query_one("#files-list", ListView)
        try:
            index = list_view.index
        except Exception:
            return
        if index is None or index >= len(files):
            return
        self._load_document(files[index])

    def _load_document(self, path: Path) -> None:
        view = self.query_one("#doc-view", Static)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            view.update(f"cannot read {path}: {exc}")
            return
        if path.suffix == ".md":
            view.update(Markdown(text))
        elif path.suffix == ".json":
            view.update(Syntax(text, "json", theme="ansi_dark", word_wrap=True))
        else:
            lines = tail_file(path, 400)
            view.update("\n".join(lines))
