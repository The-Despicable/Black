"""Chat screen — a scrolling conversation with the thinking brain.

Runs the real ``raphael-ma chat`` command through the engine (governance,
brain journal, transcripts all still apply). The pane keeps the full
conversation across turns; each reply is one NDJSON line from ``--json``
mode, which this screen renders as chat bubbles instead of raw JSON.

v2: session resume — pick any past chat from the history table (or paste a
session id) and the full transcript is restored as bubbles via
``brain log --session <id> --full``; every bubble is timestamped; assistant
turns show provider/model plus the insights the brain recalled; a status
line under the pane tracks the session id / turn count and shows a waiting
indicator while a reply is being generated.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Footer, Input, Label, OptionList, RichLog, Static

from raphael.multiagent.tui.engine import RunResult
from raphael.multiagent.tui.screens.base import RaphaelScreen
from raphael.multiagent.tui.widgets import (
    CommandBar,
    OutputPane,
    ResultBanner,
    StatusStrip,
    latest_models_row,
    parse_ndjson,
    populate_table_fixed,
)

WRAP = 70
YOU_COLOR = "#39bae6"
BOT_COLOR = "#3fd084"

CHAT_SESSION_COLS = [
    ("id", "Session", None),
    ("topic", "Topic", 42),
    ("started", "Started", 16),
    ("turns", "Turns", None),
]


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
    SHOWS_BRAIN_STRIP = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.session_id: Optional[str] = None
        self._turns_shown = 0

    # ------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield StatusStrip(id="strip")
        pane = ChatPane(id="chat")
        pane.styles.height = "1fr"
        yield pane
        yield Static("", id="chat-status")
        with Horizontal(classes="form-row chat-toolbar"):
            yield Input(
                placeholder="say something… (enter to send)",
                id="chat-msg",
            )
            yield Button("Send", id="chat-send", variant="primary")
            yield Button("New", id="chat-new")
        with Horizontal(classes="form-row chat-toolbar"):
            yield Label("resume")
            yield Input(placeholder="session id", id="chat-resume", classes="narrow")
            yield Button("resume", id="chat-resume-btn")
            yield Button("history", id="chat-history")
            yield Button("clear view", id="chat-clear")
        sessions = DataTable(id="chat-sessions")
        sessions.display = False
        yield sessions
        with Horizontal(classes="form-row chat-toolbar"):
            yield Label("provider")
            yield Input(
                placeholder="nvidia | ollama-cloud | inferx (blank = roles.chat)",
                id="chat-provider",
            )
            yield Label("model")
            yield Input(
                placeholder="pick from the list, or type an id (blank = default)",
                id="chat-model",
            )
            yield Button("live models", id="chat-models")
            yield Button("bind as default", id="chat-bind")
        picker = OptionList(id="chat-model-list")
        picker.styles.height = 8
        picker.display = False
        yield picker
        output = OutputPane(id="output")
        output.display = False  # chat renders itself; hidden for pane-less commands
        yield output
        yield CommandBar(id="cmdbar")
        yield ResultBanner(id="result")
        yield Footer()

    def on_mount(self) -> None:
        self._live_models: List[str] = []
        self._chat_session_rows: List[Dict[str, Any]] = []
        self.set_interval(0.5, self._tick_status)
        self._tick_status()

    def on_show(self) -> None:
        super().on_show()
        try:
            self.query_one("#chat-msg", Input).focus()
        except Exception:
            pass

    def chat_pane(self) -> ChatPane:
        return self.query_one("#chat", ChatPane)

    # ------------------------------------------------------------ bubbles
    def _bubble_header(self, who: str, meta: str = "") -> str:
        ts = time.strftime("%H:%M")
        color = YOU_COLOR if who == "you" else BOT_COLOR
        head = f"[dim]{ts}[/dim] [bold {color}]▸ {who}[/bold {color}]"
        if meta:
            head += f" [dim]· {escape(meta)}[/dim]"
        return head

    def _write_bubble(self, who: str, text: str, meta: str = "") -> None:
        pane = self.chat_pane()
        pane.write(self._bubble_header(who, meta))
        for chunk in _wrap_reply(text or ""):
            pane.write(chunk)
        pane.write("")
        self._turns_shown += 1
        pane.scroll_end(animate=False)

    # ---------------------------------------------------------- statusline
    def _tick_status(self) -> None:
        try:
            status = self.query_one("#chat-status")
        except Exception:
            return
        state = self.app.state  # type: ignore[attr-defined]
        if state.busy:
            status.set_classes("busy")
            status.update("⠋ waiting for the assistant…")
        else:
            status.set_classes("ready")
            sid = self.session_id or "new conversation"
            status.update(f"ready · session {sid} · {self._turns_shown} turn(s) shown")

    # -------------------------------------------------------------- send
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-msg":
            self.query_one("#chat-send", Button).press()
        elif event.input.id == "chat-resume":
            self.query_one("#chat-resume-btn", Button).press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "chat-send":
            self._send()
        elif event.button.id == "chat-new":
            self.session_id = None
            self._turns_shown = 0
            self.chat_pane().clear()
            self.app.notify("started a new conversation (the old session stays in the brain)", title="Chat")
        elif event.button.id == "chat-clear":
            self.chat_pane().clear()
        elif event.button.id == "chat-resume-btn":
            sid = str(self._value("#chat-resume") or "").strip()
            if sid:
                self._resume_session(sid)
        elif event.button.id == "chat-history":
            self._toggle_history()
        elif event.button.id == "chat-models":
            self._load_models()
        elif event.button.id == "chat-bind":
            self._bind()

    # ------------------------------------------------------- model picker
    def _load_models(self) -> None:
        provider = str(self._value("#chat-provider") or "").strip()
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
        provider = str(self._value("#chat-provider") or "").strip()
        model = str(self._value("#chat-model") or "").strip()
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

    # ------------------------------------------------------------ history
    def _toggle_history(self) -> None:
        table = self.query_one("#chat-sessions", DataTable)
        table.display = not table.display
        if table.display and not table.row_count:
            self._load_history_table()

    def _load_history_table(self, background: bool = False) -> None:
        self.run_command(
            ["brain", "sessions", "--limit", "30"],
            json_mode=True,
            label="chat history",
            background=background,
            on_done=self._fill_history_table,
        )

    def _fill_history_table(self, res: RunResult) -> None:
        if not res.ok:
            return
        rows = [r for r in parse_ndjson(res.out) if str(r.get("kind")) == "chat"]
        # newest first from the CLI; add a turn-count placeholder the resume fills
        self._chat_session_rows = rows
        table = self.query_one("#chat-sessions", DataTable)
        populate_table_fixed(table, rows, CHAT_SESSION_COLS)
        if rows:
            self.app.notify(
                f"{len(rows)} chat session(s) — click a row to resume it",
                title="Chat", timeout=4,
            )
        else:
            self.app.notify("no past chat sessions yet", title="Chat", timeout=4)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "chat-sessions":
            return
        try:
            idx = int(event.row_key.value or -1)
        except (TypeError, ValueError):
            return
        rows = self._chat_session_rows
        if idx < 0 or idx >= len(rows):
            return
        sid = str(rows[idx].get("id") or "")
        if sid:
            self.query_one("#chat-resume", Input).value = sid
            self._resume_session(sid)

    def _resume_session(self, session_id: str) -> None:
        pane = self.chat_pane()
        pane.clear()
        self._turns_shown = 0
        pane.write(f"[dim]— restoring session {escape(session_id)} … —[/dim]")

        def done(res: RunResult) -> None:
            if not res.ok:
                pane.write(f"[#f38ba8]✗ could not load session {escape(session_id)}[/]")
                return
            rows = [r for r in parse_ndjson(res.out) if str(r.get("agent")) not in ("(empty)",)]
            rows = list(reversed(rows))  # CLI emits latest-first
            pane.clear()
            if not rows:
                pane.write(f"[dim]— session {escape(session_id)} has no turns —[/dim]")
            self.session_id = session_id
            for r in rows:
                agent = str(r.get("agent"))
                who = "you" if agent == "user" else "assistant"
                at = str(r.get("at") or "")[:16]
                body = str(r.get("content") or r.get("excerpt") or "")
                self._write_bubble(who, body, meta=f"restored {at}" if at else "")
            pane.scroll_end(animate=False)

        self.run_command(
            ["brain", "log", "--last", "500", "--session", session_id, "--full"],
            json_mode=True,
            label="restore chat",
            on_done=done,
        )

    # -------------------------------------------------------------- turn
    def _send(self) -> None:
        app = self.app
        state = app.state  # type: ignore[attr-defined]
        if state.busy:
            app.notify("A command is already running — wait for the reply.", title="Busy", severity="warning")
            return
        message = str(self._value("#chat-msg") or "").strip()
        if not message:
            app.notify("Type a message first.", title="Chat", severity="warning")
            return
        provider = str(self._value("#chat-provider") or "").strip()
        model = str(self._value("#chat-model") or "").strip()
        if (provider or model) and not (provider and model):
            app.notify("provider and model must both be set (or both blank)", title="Chat", severity="warning")
            return
        pane = self.chat_pane()
        self._write_bubble("you", message)
        try:
            self.query_one("#chat-msg", Input).value = ""
        except Exception:
            pass
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
            pane.write(f"[dim]— chat session {new_sid} —[/dim]")
        reply = str(row.get("reply") or "")
        model = str(row.get("model") or "")
        meta_bits = [b for b in (str(row.get("provider") or ""), model) if b]
        used = row.get("insights_used") or []
        if isinstance(used, (list, tuple)) and used:
            ids = " ".join(f"#{i}" for i in list(used)[:6])
            more = f" +{len(used) - 6}" if len(used) > 6 else ""
            meta_bits.append(f"brain recalled {ids}{more}")
        self._write_bubble("assistant", reply, meta=" · ".join(meta_bits))


def _wrap_reply(reply: str) -> List[str]:
    """Wrap long replies into RichLog-safe lines (preserve blank lines)."""
    import textwrap

    out: List[str] = []
    for raw_line in (reply or "").rstrip().split("\n"):
        for piece in (textwrap.wrap(raw_line, WRAP) or [""]):
            out.append(escape(piece))
    return out
