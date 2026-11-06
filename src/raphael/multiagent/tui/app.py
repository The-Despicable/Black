"""RaphaelTUI — Textual application wiring every raphael-ma command group."""

from __future__ import annotations

import argparse
from typing import Any, Dict, Optional, Type

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Static

from raphael.multiagent.tui.engine import Engine
from raphael.multiagent.tui.state import AppState
from raphael.multiagent.tui.theme import MISSION_CONTROL_CSS

from raphael.multiagent.tui.screens.dashboard import DashboardScreen
from raphael.multiagent.tui.screens.debate import DebateScreen
from raphael.multiagent.tui.screens.community import CommunityScreen
from raphael.multiagent.tui.screens.teams import TeamsScreen
from raphael.multiagent.tui.screens.brain import BrainScreen
from raphael.multiagent.tui.screens.providers import ProvidersScreen
from raphael.multiagent.tui.screens.governance import GovernanceScreen
from raphael.multiagent.tui.screens.benchmark import BenchmarkScreen
from raphael.multiagent.tui.screens.transcript import TranscriptScreen
from raphael.multiagent.tui.screens.json_inspect import JsonConsoleScreen
from raphael.multiagent.tui.screens.chat import ChatScreen
from raphael.multiagent.tui.screens.base import ConfirmModal, HelpModal

SCREENS: Dict[str, Type[Screen]] = {
    "dashboard": DashboardScreen,
    "debate": DebateScreen,
    "chat": ChatScreen,
    "community": CommunityScreen,
    "teams": TeamsScreen,
    "brain": BrainScreen,
    "providers": ProvidersScreen,
    "governance": GovernanceScreen,
    "benchmark": BenchmarkScreen,
    "transcripts": TranscriptScreen,
    "json": JsonConsoleScreen,
}

BINDINGS = [
    Binding("f1", "screen('dashboard')", "Dashboard", priority=True),
    Binding("f2", "toggle_mode", "Arm mock/live", priority=True),
    Binding("f3", "screen('debate')", "Debate", priority=True),
    Binding("f4", "screen('community')", "Community", priority=True),
    Binding("f5", "screen('teams')", "Teams", priority=True),
    Binding("f6", "screen('brain')", "Brain", priority=True),
    Binding("f7", "screen('providers')", "Providers", priority=True),
    Binding("f8", "screen('governance')", "Governance", priority=True),
    Binding("f9", "screen('benchmark')", "Benchmark", priority=True),
    Binding("f10", "screen('transcripts')", "Transcripts", priority=True),
    Binding("f11", "screen('json')", "JSON console", priority=True),
    Binding("f12", "screen('chat')", "Chat", priority=True),
    Binding("question_mark", "help", "Help", priority=True),
    Binding("escape", "screen('dashboard')", "Back", priority=True),
    Binding("q", "quit", "Quit"),
    Binding("ctrl+q", "quit", "Quit", priority=True),
]


class RaphaelTUI(App):  # type: ignore[misc]
    CSS = MISSION_CONTROL_CSS
    TITLE = "raphael-ma · mission console"
    SUB_TITLE = "self-evolving multi-agent CLI — debates · communities · model teams · brain"

    BINDINGS = BINDINGS

    def __init__(self, home: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = AppState(home=home)
        self.engine = Engine(self.state.home)

    # ------------------------------------------------------------------
    def _get_dom_base(self):  # type: ignore[override]
        """Textual 8 routes App-level DOM queries to the *default* screen; the
        mission console expects the classic behavior of querying the ACTIVE
        screen, so every screen's widgets are reachable via ``app.query``."""
        try:
            return self.screen
        except Exception:
            return super()._get_dom_base()

    def on_mount(self) -> None:
        self.dark = True
        for name, cls in SCREENS.items():
            self.install_screen(cls(), name=name)
        # push (not switch) the first screen: the implicit default screen has
        # no result-callback entry, and switch_screen away from it would fail.
        self.push_screen("dashboard")
        self.run_worker(self._probe_engine, thread=True, group="probe", name="engine-probe")

    def _probe_engine(self) -> None:
        ok, path, error = self.engine.probe()

        def apply() -> None:
            self.state.set_engine(ok, path, error)
            if ok:
                self.notify(f"engine ready — {path}", title="raphael-ma", timeout=4)
            else:
                self.notify(
                    "raphael.multiagent.cli is not importable. Run screens will report "
                    "'engine unavailable' until PYTHONPATH includes the repository src/ dir.",
                    title="Engine missing",
                    severity="warning",
                    timeout=10,
                )

        try:
            self.call_from_thread(apply)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # actions ------------------------------------------------------------
    def action_screen(self, name: str) -> None:
        target = SCREENS.get(name)
        if target is None:
            return
        current = self.screen
        if isinstance(current, target):
            return
        if self.state.busy:
            self.notify(
                "A command is running — wait for it to finish before switching screens.",
                title="Busy",
                severity="warning",
            )
            return
        self.switch_screen(name)
        self._refresh_screen(name)

    def _refresh_screen(self, name: str) -> None:
        """Installed screens stay mounted across switches and ScreenResume
        does not re-fire on_show — refresh returning screens explicitly."""
        try:
            target = self.get_screen(name)
            if getattr(target, "is_mounted", False):
                target.call_after_refresh(target.refresh_on_show)
        except Exception:
            pass

    def action_toggle_mode(self) -> None:
        self.state.armed_live = not self.state.armed_live
        if self.state.armed_live:
            self.notify(
                "LIVE armed — commands now run with --live against real providers.",
                title="Mode",
                severity="warning",
            )
        else:
            self.notify("Mock mode — commands run with explicit --mock.", title="Mode")
        try:
            self.screen.refresh_strip()
        except Exception:
            pass
        # keep the dashboard's mode panel in sync even when toggled elsewhere
        if self.screen is not self.get_screen("dashboard"):
            self._refresh_screen("dashboard")

    def action_help(self) -> None:
        if not isinstance(self.screen, HelpModal):
            self.push_screen(HelpModal())

    def action_quit(self) -> None:
        if self.state.busy:
            self.push_screen(
                ConfirmModal(
                    "A command is still running.\nQuit anyway? The CLI session's audit trail "
                    "records what was already persisted; unfinished output is lost.",
                ),
                callback=self._confirm_quit,
            )
        else:
            self.exit()

    def _confirm_quit(self, confirmed: bool) -> None:
        if confirmed:
            self.exit()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="raphael-ma-tui",
        description="Textual mission console for the raphael-ma multi-agent CLI.",
    )
    parser.add_argument(
        "--home",
        default=None,
        help="raphael-ma home directory (default: $RAPHAEL_MA_HOME or ~/.raphael/ma)",
    )
    args = parser.parse_args()
    RaphaelTUI(home=args.home).run()
