"""Run-screen tests: chat / community / debate TUI v2 + their JSON surface.

Covers the completed run-screen work:
* ``--json`` stdout of chat / community / debate is pure NDJSON — one turn
  event per agent turn plus one final result object — and carries the fields
  the screens render (insights_used, participants + scores, winner +
  scores + session_id);
* ``brain log --full`` returns untruncated content (chat transcript restore);
* the screens themselves: chat send → bubbles + resume from history,
  community run → live pane + synthesis panel + participant scores,
  debate run → verdict panel with winner badge, dashboard brain digest.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from textual.widgets import Button, DataTable, Input, RichLog, Static
from typer.testing import CliRunner

from raphael.multiagent.cli import app

runner = CliRunner()
# stdout-only capture: --json purity is asserted strictly (status messages
# belong on stderr). Click >= 8.2 removed ``mix_stderr``; ``Result.stdout``
# is now the dedicated stdout stream, while ``Result.output`` mixes both.
strict_runner = CliRunner()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RAPHAEL_MA_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "home"


@pytest.fixture()
def populated_home(home):
    assert runner.invoke(app, ["init"]).exit_code == 0
    return home


def _json_lines(output: str):
    """Parse stdout of --json mode; every line must be one JSON object."""
    lines = [ln for ln in output.splitlines() if ln.strip()]
    objs = [json.loads(ln) for ln in lines]  # raises on any non-JSON line
    return objs


# ---------------------------------------------------------------------------
# CLI JSON surface


def test_chat_json_turn_event_and_result(populated_home):
    res = strict_runner.invoke(app, ["--json", "chat", "hello there", "--no-stream"])
    assert res.exit_code == 0, res.output
    objs = _json_lines(res.stdout)
    events = [o for o in objs if o.get("event") == "turn"]
    finals = [o for o in objs if "reply" in o]
    assert events, "expected at least one turn event"
    assert finals, "expected the final result object"
    ev = events[-1]
    for key in ("agent", "text", "model", "provider", "latency_ms", "ok", "session_id"):
        assert key in ev, f"turn event missing {key}"
    final = finals[-1]
    for key in ("session_id", "reply", "provider", "model", "insights_used", "turns"):
        assert key in final, f"chat result missing {key}"
    assert isinstance(final["insights_used"], list)
    assert final["turns"] >= 2  # user turn + assistant reply


def test_community_json_pure_ndjson_with_scores(populated_home):
    res = strict_runner.invoke(
        app,
        ["--json", "community", "tabs vs spaces", "--agents", "2",
         "--rounds", "1", "--no-stream"],
    )
    assert res.exit_code == 0, res.output
    objs = _json_lines(res.stdout)
    # stdout mixes: turn events (dicts) + the CLI's summary tables (arrays,
    # documented --json behavior) + the final result object (dict)
    events = [o for o in objs if isinstance(o, dict) and o.get("event") == "turn"]
    finals = [o for o in objs if isinstance(o, dict) and "synthesis" in o]
    assert len(events) >= 2  # two specialists + moderator ask
    assert finals, "expected the final synthesis object"
    final = finals[-1]
    for key in ("kind", "session_id", "topic", "participants", "synthesis",
                "consensus", "dissent", "open_questions"):
        assert key in final, f"community result missing {key}"
    assert final["kind"] == "community"
    assert len(final["participants"]) == 2
    for p in final["participants"]:
        assert {"agent", "persona", "model", "score", "turns"} <= set(p)
        assert isinstance(p["score"], float)


def test_debate_json_verdict_enriched(populated_home):
    res = strict_runner.invoke(
        app, ["--json", "debate", "cats rule", "--rounds", "1", "--no-stream"]
    )
    assert res.exit_code == 0, res.output
    objs = _json_lines(res.stdout)
    final = objs[-1]
    assert "winner" in final and "scores" in final
    assert final["session_id"], "verdict must carry the session id"
    assert final.get("motion") == "cats rule"
    assert set(final["scores"]) >= {"pro", "con"}


def test_brain_log_full_returns_untruncated_content(populated_home):
    assert runner.invoke(app, ["--json", "chat", "tell me something long", "--no-stream"]).exit_code == 0
    res = strict_runner.invoke(app, ["--json", "brain", "log", "--last", "5", "--full"])
    assert res.exit_code == 0, res.output
    objs = _json_lines(res.stdout)
    rows = objs[0]
    assert rows
    r = rows[0]
    assert "content" in r, "--full must add the untruncated content field"
    assert len(r["content"]) > len(r["excerpt"])


# ---------------------------------------------------------------------------
# pilot: the screens themselves

async def _wait_idle(app, pilot, timeout_s: float = 25.0):
    await pilot.pause(0.5)
    for _ in range(int(timeout_s / 0.25)):
        await pilot.pause(0.25)
        if not app.state.busy:
            return
    await pilot.pause(0.5)


async def _wait_table(app, pilot, table, timeout_s: float = 25.0):
    await pilot.pause(0.5)
    for _ in range(int(timeout_s / 0.25)):
        await pilot.pause(0.25)
        if not app.state.busy and table.row_count > 0:
            return
    await pilot.pause(0.5)


async def test_chat_screen_bubbles_and_resume(populated_home):
    from raphael.multiagent.tui.app import RaphaelTUI

    app = RaphaelTUI(home=str(populated_home))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("f12")
        screen = app.screen
        assert type(screen).__name__ == "ChatScreen"

        # send a message → bubbles for both sides + session captured
        screen.query_one("#chat-msg", Input).value = "hello brain"
        await pilot.click("#chat-send")
        await _wait_idle(app, pilot)
        pane = screen.query_one("#chat", RichLog)
        rendered = "\n".join(ln.text for ln in pane.lines)
        assert "you" in rendered and "hello brain" in rendered
        assert "assistant" in rendered
        assert screen.session_id, "session id must be captured after the first turn"

        # history table lists the chat session; clicking restores the transcript
        await pilot.click("#chat-history")
        table = screen.query_one("#chat-sessions", DataTable)
        await _wait_table(app, pilot, table)
        assert table.row_count == 1
        table.post_message(DataTable.RowSelected(table, 0, table.ordered_rows[0].key))
        await _wait_idle(app, pilot)
        await pilot.pause(0.3)
        rendered = "\n".join(ln.text for ln in pane.lines)
        assert "restoring" in rendered or "hello brain" in rendered
        assert screen.session_id  # still bound after restore


async def test_community_screen_synthesis_and_scores(populated_home):
    from raphael.multiagent.tui.app import RaphaelTUI

    app = RaphaelTUI(home=str(populated_home))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("f4")
        screen = app.screen
        assert type(screen).__name__ == "CommunityScreen"

        screen.query_one("#topic", Input).value = "tabs vs spaces"
        screen.query_one("#agents").value = 2  # options hold ints
        await pilot.click("#run")
        await _wait_idle(app, pilot)

        # live pane rendered the specialist turns
        live = screen.query_one("#community-live", RichLog)
        live_text = "\n".join(ln.text for ln in live.lines)
        assert "RESEARCHER" in live_text or "ANALYST" in live_text

        # synthesis panel carries the moderator output + session link
        synth = screen.query_one("#community-synthesis", Static)
        synth_text = str(synth.render())
        assert "session" in synth_text
        assert synth_text != "(run a round-table — the moderator's synthesis lands here)"

        # participants table scored both agents
        parts = screen.query_one("#community-participants", DataTable)
        assert parts.row_count == 2


async def test_debate_screen_verdict_panel(populated_home):
    from raphael.multiagent.tui.app import RaphaelTUI

    app = RaphaelTUI(home=str(populated_home))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("f3")
        screen = app.screen
        assert type(screen).__name__ == "DebateScreen"

        screen.query_one("#motion", Input).value = "cats rule"
        await pilot.click("#run")
        await _wait_idle(app, pilot)

        verdict = screen.query_one("#verdict", Static)
        text = str(verdict.render())
        assert "Winner:" in text
        assert "PRO" in text and "CON" in text
        assert "session" in text  # links back to the brain

        # live pane streamed the speeches
        live = screen.query_one("#debate-live", RichLog)
        live_text = "\n".join(ln.text for ln in live.lines)
        assert live_text.strip(), "debate turns should stream into the live pane"


async def test_dashboard_brain_digest_and_strip(populated_home):
    from raphael.multiagent.tui.app import RaphaelTUI
    from raphael.multiagent.tui.widgets import StatusStrip

    app = RaphaelTUI(home=str(populated_home))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        assert type(screen).__name__ == "DashboardScreen"
        # chained background loads settle
        await _wait_idle(app, pilot)
        await pilot.pause(1.0)
        await _wait_idle(app, pilot)
        home_text = str(screen.query_one("#home-panel", Static).render())
        assert "insights" in home_text, "brain digest should land on the home panel"
        strip_text = str(screen.query_one("#strip-brain", Static).render())
        assert "insights" in strip_text
        # engine badge + clock are part of the strip now
        assert screen.query_one("#strip-engine")
        assert screen.query_one("#strip-clock")


async def test_turn_event_pane_renders_events(populated_home):
    from raphael.multiagent.tui.app import RaphaelTUI
    from raphael.multiagent.tui.widgets import TurnEventPane

    app = RaphaelTUI(home=str(populated_home))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("f4")
        screen = app.screen
        pane = screen.query_one("#community-live", TurnEventPane)
        # feed the renderer directly (unit level, inside an app context)
        pane._render_stdout_line(json.dumps({
            "event": "turn", "agent": "RESEARCHER", "text": "first point",
            "model": "m1", "provider": "nvidia", "round": 1,
            "latency_ms": 12.3, "ok": True,
        }))
        pane._render_stdout_line("not json at all")
        pane._render_stdout_line(json.dumps({"reply": "final result object"}))
        text = "\n".join(ln.text for ln in pane.lines)
        assert "RESEARCHER" in text and "first point" in text
        assert "not json at all" in text  # non-JSON passthrough (dim)
        assert "final result object" not in text  # results are NOT rendered here
