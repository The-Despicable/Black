"""Chat screen — a scrolling conversation with the thinking brain.

Runs the real ``raphael-ma chat`` command through the engine (governance,
brain journal, transcripts all still apply). The pane keeps the full
conversation across turns; each reply is one NDJSON line from ``--json``
mode, which this screen renders as chat bubbles instead of raw JSON.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Input, OptionList, Label, RichLog

from raphael.multiagent.tui.engine import RunResult
from raphael.multiagent.tui.screens.base import RaphaelScreen
from raphael.multiagent.tui.widgets import CommandBar, OutputPane, ResultBanner, StatusStrip, latest_models_row, parse_ndjson

WRAP = 70


class ChatPane(RichLog):
    """Conversation log. Unlike OutputPane it never clears between turns and
    never echoes raw stdout — the screen renders replies itself; only live
    stderr warnings are polled so problems stay visible while streaming."""

    _POLL_ERR = 0.12

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(wrap=True, markup=True, max_lines=4000, **kwargs)
        self._engine: Any = None
        self._timer: Any = None

    # pane API faithful to OutputPane ------------------------------------
    def bind_engine(self, engine: Any) -> None:
        self._engine = engine
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_interval(self._POLL_ERR, self._poll)

    def reset_stream(self) -> None:
        pass  # a chat window keeps its history

    def _poll(self) -> None:
        if self._engine is None:
            return
        for line in self._engine.poll_err_lines():
            self.write(Text(line, style="dim"))

    def finalize(self, res: RunResult) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._engine = None


class ChatScreen(RaphaelScreen):
    TITLE = "raphael-ma · chat"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.session_id: Optional[str] = None

    # ------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield StatusStrip(id="strip")
        pane = ChatPane(id="chat")
        pane.styles.height = "1fr"
        yield pane
        output = OutputPane(id="output")
        output.display = False
        yield output
        with Horizontal(classes="form-row"):
            yield Input(
                placeholder="say something… (enter to send)",
                id="chat-msg",
            )
            yield Button("Send", id="chat-send", variant="primary")
            yield Button("New", id="chat-new")
        with Horizontal(classes="form-row"):
            yield Label("provider")
            yield Input(
                placeholder="nvidia | ollama-cloud | inferx (blank = roles.chat)",
                id="chat-provider",
            )
            yield Button("live models", id="chat-models")
        with Horizontal(classes="form-row"):
            yield Label("model")
            yield Input(
                placeholder="pick from the list, or type an id (blank = default)",
                id="chat-model",
            )
            yield Button("bind as default", id="chat-bind")
        picker = OptionList(id="chat-model-list")
        picker.styles.height = 8
        picker.display = False
        yield picker
        yield CommandBar(id="cmdbar")
        yield ResultBanner(id="result")
        yield Footer()

    def on_mount(self) -> None:
        self._live_models: List[str] = []

    def chat_pane(self) -> ChatPane:
        return self.query_one("#chat", ChatPane)

    # -------------------------------------------------------------- send
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-msg":
            self.query_one("#chat-send", Button).press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "chat-send":
            self._send()
        elif event.button.id == "chat-new":
            self.session_id = None
            self.chat_pane().clear()
        elif event.button.id == "chat-models":
            self._load_models()
        elif event.button.id == "chat-bind":
            self._bind()

    def _load_models(self) -> None:
        provider = self._value("#chat-provider").strip()
        if not provider:
            self.app.notify("Type a provider name first (nvidia, ollama-cloud, inferx).", title="Chat", severity="warning")
            return
        self.run_command(
            ["providers", "models", provider],
            json_mode=True,
            label="live models",
            on_done=self._fill_models,
        )

    def _fill_models(self, res) -> None:
        row = latest_models_row(res)
        if not row:
            self.app.notify("No live model list returned.", title="Chat", severity="warning")
            return
        self._live_models = [str(m) for m in row["models"]]
        picker = self.query_one("#chat-model-list", OptionList)
        picker.clear_options()
        picker.add_options(self._live_models)
        picker.display = True
        self.app.notify(f"{len(self._live_models)} live models — click one to fill the model input", title="Chat")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        try:
            choice = str(self._live_models[event.option_index])
        except Exception:
            return
        self.query_one("#chat-model", Input).value = choice

    def _bind(self) -> None:
        provider = self._value("#chat-provider").strip()
        model = self._value("#chat-model").strip()
        if not provider or not model:
            self.app.notify("provider and model are both required to bind", title="Chat", severity="warning")
            return
        self.run_command(
            ["providers", "select", provider, "--model", model, "--role", "chat"],
            json_mode=True,
            label="bind chat default",
            on_done=lambda res: self.app.notify(
                "chat default bound" if res.ok else "bind failed", title="Chat",
                severity=("information" if res.ok else "error"),
            ),
        )

    def _send(self) -> None:
        app = self.app
        state = app.state  # type: ignore[attr-defined]
        if state.busy:
            app.notify("A command is already running — wait for the reply.", title="Busy", severity="warning")
            return
        message = self._value("#chat-msg").strip()
        if not message:
            app.notify("Type a message first.", title="Chat", severity="warning")
            return
        provider = self._value("#chat-provider").strip()
        model = self._value("#chat-model").strip()
        if (provider or model) and not (provider and model):
            app.notify("provider and model must both be set (or both blank)", title="Chat", severity="warning")
            return
        pane = self.chat_pane()
        pane.write(f"[bold #74c7ec]you[/] {escape(message)}")
        argv: List[str] = ["chat", message]
        if self.session_id:
            argv += ["--session", self.session_id]
        if provider and model:
            argv += ["--provider", provider, "--model", model]
        argv += list(self.mode_flags())
        argv.append("--no-stream")
        self.run_command(argv, json_mode=True, pane=pane, label="chat", on_done=self._on_turn)

    def _on_turn(self, res: RunResult) -> None:
        pane = self.chat_pane()
        if not res.ok:
            first_err = next((ln for ln in res.err_lines if ln.strip()), "")
            pane.write(f"[#f38ba8]✗ turn stopped[/] [dim]{escape(first_err[:120])}[/dim]")
            return
        rows = parse_ndjson(res.out)
        row: Dict[str, Any] = {}
        for candidate in rows:
            if isinstance(candidate, dict) and "reply" in candidate:
                row = candidate
        if not row:
            pane.write("[#f9e2af]? no reply in CLI output[/]")
            return
        new_sid = str(row.get("session_id") or "")
        if new_sid and new_sid != self.session_id:
            self.session_id = new_sid
            pane.write(f"[dim]— chat session {new_sid} —[/]")
        reply = str(row.get("reply") or "")
        model = str(row.get("model") or "")
        meta = f"{row.get('provider', '')}/{model}" if model else str(row.get("provider", ""))
        pane.write(f"[bold #a6e3a1]assistant[/] [dim]· {escape(meta)}[/dim]")
        for chunk in _wrap_reply(reply):
            pane.write(chunk)
        pane.write("")  # spacing between turns
        pane.scroll_end(animate=False)


def _wrap_reply(reply: str) -> List[str]:
    """Wrap long replies into RichLog-safe lines (preserve blank lines)."""
    import textwrap

    out: List[str] = []
    for raw_line in (reply or "").rstrip().split("\n"):
        for piece in (textwrap.wrap(raw_line, WRAP) or [""]):
            out.append(escape(piece))
    return out
