"""Base screen: status strip, command bar, output pane, result banner."""

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Static

from raphael.multiagent.tui.engine import RunResult
from raphael.multiagent.tui.widgets import CommandBar, OutputPane, ResultBanner, StatusStrip


class RaphaelScreen(Screen):  # type: ignore[misc]
    TITLE = "raphael-ma"

    def compose(self) -> ComposeResult:
        yield StatusStrip(id="strip")
        with VerticalScroll(id="body"):
            yield from self.compose_body()
        yield CommandBar(id="cmdbar")
        yield OutputPane(id="output")
        yield ResultBanner(id="result")
        yield Footer()

    def compose_body(self) -> ComposeResult:
        yield Static("")

    def on_show(self) -> None:
        self.refresh_strip()

    def refresh_on_show(self) -> None:
        """Explicit refresh hook for returning to this screen.

        Installed screens stay mounted when switched away, and ScreenResume
        does not re-fire on_show — so the app calls this after switching."""
        self.refresh_strip()

    def refresh_strip(self) -> None:
        try:
            strip = self.query_one(StatusStrip)
            strip._refresh()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # command execution — always through the real Typer surface ----------
    def run_command(
        self,
        argv: Sequence[str],
        *,
        json_mode: bool = False,
        pane: Optional[OutputPane] = None,
        on_done: Optional[Callable[[RunResult], None]] = None,
        label: str = "",
    ) -> None:
        app = self.app
        state = app.state  # type: ignore[attr-defined]
        if state.busy:
            app.notify(
                "A command is already running — wait for it to finish.",
                title="Busy",
                severity="warning",
            )
            return
        full = state.augment(list(argv), json_mode=json_mode)
        pane = pane if pane is not None else self.query_one("#output", OutputPane)
        banner = self.query_one("#result", ResultBanner)
        cmdbar = self.query_one("#cmdbar", CommandBar)
        cmdbar.set_argv(full)
        pane.reset_stream()
        banner.set_running(full, label)
        state.busy = True
        engine = app.engine  # type: ignore[attr-defined]

        def work() -> None:
            res = engine.run(full)

            def done() -> None:
                pane.finalize(res)
                banner.set_result(res)
                state.busy = False
                state.last_result = res
                self._notify_result(app, res)
                if on_done is not None:
                    on_done(res)

            try:
                app.call_from_thread(done)
            except Exception:
                pass

        pane.bind_engine(engine)
        self.run_worker(work, thread=True, group="cmd", name=label or "command")

    @staticmethod
    def _notify_result(app: Any, res: RunResult) -> None:
        if res.code == 3:
            app.notify(
                "Governance kill-switch engaged — session aborted (exit 3).",
                title="Kill switch",
                severity="error",
            )
        elif res.code == 4:
            app.notify(
                "Governance configuration error (exit 4).",
                title="Governance",
                severity="error",
            )
        elif res.code == -1:
            app.notify(
                "Engine unavailable — set PYTHONPATH to the repository src/ directory.",
                title="Engine",
                severity="error",
            )

    # helpers -------------------------------------------------------------
    def mode_flags(self) -> Sequence[str]:
        state = self.app.state  # type: ignore[attr-defined]
        return state.mode_flags()

    def _value(self, selector: str, attr: str = "value", default: Any = "") -> Any:
        try:
            widget = self.query_one(selector)
            return getattr(widget, attr, default)
        except Exception:
            return default


# ---------------------------------------------------------------------------
# modals


class HelpModal(ModalScreen):  # type: ignore[misc]
    BINDINGS = [("escape", "dismiss", "Close")]

    def action_dismiss(self) -> None:
        self.dismiss()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-dialog"):
            yield Static("raphael-ma · mission console — keys", classes="section-label")
            yield Static(
                "\n".join(
                    [
                        "F1  dashboard        F2  arm mock/live     F3  debate",
                        "F4  community        F5  team workspace    F6  brain",
                        "F7  providers        F8  governance        F9  benchmark",
                        "F10 transcripts      F11 JSON console      F12 chat  ?  help",
                        "Esc back to dashboard   q / ctrl+q quit",
                    ]
                )
            )
            yield Static("screens", classes="section-label")
            yield Static(
                "\n".join(
                    [
                        "Dashboard      home, mode, engine, governance + quick actions",
                        "Debate         motion vs rounds — PRO/CON/judge, live CLI stream",
                        "Chat           one conversation, send/receive, memory-aware",
                        "Community      topic, 2–6 agents — synthesis & scoring",
                        "Teams          YAML team plan, mission, integration, parallel",
                        "Brain          status · insights · search · log · sessions · evolve · danger",
                        "Providers      list / test / models",
                        "Governance     status, kill-switch & audit tail (read-only)",
                        "Benchmark      run across providers, table + bars",
                        "Transcripts    markdown transcripts, session JSON, audit log",
                        "JSON console   free-form argv with --json NDJSON inspection",
                    ]
                )
            )
            yield Static("safety", classes="section-label")
            yield Static(
                "\n".join(
                    [
                        "• mock by default — every run passes an explicit --mock or --live",
                        "• live only when armed with F2 (never auto-armed at launch)",
                        "• governance is never bypassed: kill-switch aborts surface as exit 3",
                        "• unrestricted governance is displayed read-only and can NOT be",
                        "  enabled from this UI — it stays an explicit config/CLI decision",
                        "• every command shows its exact argv, output and exit code",
                    ]
                )
            )
        yield Footer()


class ConfirmModal(ModalScreen):  # type: ignore[misc]
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._message = message

    def action_dismiss(self) -> None:
        self.dismiss(False)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="confirm-dialog"):
            yield Static(self._message)
            with Horizontal():
                yield Button("Confirm", id="confirm-yes", variant="error")
                yield Button("Cancel", id="confirm-no")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")
