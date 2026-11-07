"""Chat command tests — governed, memory-aware, session-replayable chat.

Processes mirror tests/test_raphael_multiagent_cli.py: in-process CliRunner
with a temp RAPHAEL_MA_HOME. Every command path still runs the real Typer
surface, the real brain DB and the real governance gate.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import raphael.multiagent.llm.openai_compat as openai_compat
from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.cli import app


def _separate_stream_runner() -> CliRunner:
    """CliRunner with stderr kept out of Result.stdout.

    The --json surface promises pure NDJSON on stdout with human
    diagnostics (banner, phase rules) on stderr. click < 8.2 mixes
    stderr into Result.stdout by default (mix_stderr=True); click >= 8.2
    removed the flag and always keeps the streams separate. Construct the
    runner accordingly so stdout assertions test the real contract.
    """
    try:
        return CliRunner(mix_stderr=False)  # click < 8.2
    except TypeError:  # click >= 8.2: streams are separate by default
        return CliRunner()


runner = _separate_stream_runner()

LIVE_MODELS = [
    "z-ai/glm-5.2",
    "deepseek-ai/deepseek-v4.1-flash",
    "qwen/qwen3-coder-480b",
    "meta/llama-4-scout",
]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RAPHAEL_MA_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)  # transcripts/ land in tmp
    assert runner.invoke(app, ["init"]).exit_code == 0
    return tmp_path / "home"


def _db(home: Path) -> BrainDB:
    db = BrainDB(home=home)
    return db


def _chat_turns(home: Path, session_id: str):
    db = _db(home)
    try:
        return db.query(
            "SELECT agent, content FROM turns WHERE session_id=? ORDER BY seq",
            (session_id,),
        )
    finally:
        db.close()


# ---------------------------------------------------------------- happy path
def test_chat_single_turn(home):
    r = runner.invoke(app, ["chat", "hello there", "--mock", "-q", "--no-stream"])
    assert r.exit_code == 0, r.output
    db = _db(home)
    try:
        rows = db.query("SELECT id FROM sessions WHERE kind='chat'")
        assert len(rows) == 1
        sid = str(rows[0]["id"])
        turns = _chat_turns(home, sid)
        assert [t["agent"] for t in turns] == ["user", "chat"]
        assert turns[0]["content"] == "hello there"
        assert turns[1]["content"].strip()
        row = db.one("SELECT transcript_path, finished_at FROM sessions WHERE id=?", (sid,))
        assert row["finished_at"]
    finally:
        db.close()


def test_chat_json_output(home):
    r = runner.invoke(app, ["--json", "chat", "status check", "--mock", "-q", "--no-stream"])
    assert r.exit_code == 0, r.output
    rows = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    obj = next(o for o in rows if "reply" in o)
    assert obj["session_id"]
    assert obj["mode"] == "mock"
    assert obj["reply"].strip()


def test_chat_session_resume(home):
    r1 = runner.invoke(app, ["--json", "chat", "first message", "--mock", "-q", "--no-stream"])
    assert r1.exit_code == 0, r1.output
    sid = json.loads(r1.stdout.strip().splitlines()[-1])["session_id"]

    r2 = runner.invoke(
        app, ["--json", "chat", "second message", "--mock", "-q", "--no-stream", "--session", sid]
    )
    assert r2.exit_code == 0, r2.output
    obj2 = json.loads(r2.stdout.strip().splitlines()[-1])
    assert obj2["session_id"] == sid

    db = _db(home)
    try:
        sessions = db.query("SELECT id FROM sessions WHERE kind='chat'")
        assert len(sessions) == 1  # resumed, not duplicated
        turns = _chat_turns(home, sid)
        assert [t["agent"] for t in turns] == ["user", "chat", "user", "chat"]
        assert turns[2]["content"] == "second message"
    finally:
        db.close()


def test_chat_rejects_unknown_session(home):
    r = runner.invoke(app, ["chat", "hi", "--mock", "-q", "--no-stream", "--session", "nosuchsession"])
    assert r.exit_code == 1
    assert "not found" in r.output

# ------------------------------------------------------------------ safety
def test_chat_kill_switch(home, monkeypatch):
    from raphael.multiagent.governance import KillSwitchEngaged
    import raphael.multiagent.orchestrators.base as base_mod

    class _LockedGovernance:
        def check(self, action, context=None):
            raise KillSwitchEngaged("kill switch engaged")

        def audit(self, event):
            pass

    monkeypatch.setattr(base_mod, "get_governance", lambda cfg: _LockedGovernance())
    r = runner.invoke(app, ["chat", "are you alive", "--mock", "-q", "--no-stream"])
    assert r.exit_code == 3


def test_chat_override_rejects_unknown_model(home, monkeypatch):
    monkeypatch.setattr(
        openai_compat.OpenAICompatProvider, "list_models", lambda self: list(LIVE_MODELS)
    )
    r = runner.invoke(
        app,
        ["chat", "hi", "--live", "--provider", "nvidia", "--model", "definitely-not-a-model", "-q", "--no-stream"],
    )
    assert r.exit_code == 1
    assert "is not served by nvidia" in r.output


def test_chat_override_accepts_known_model(home, monkeypatch):
    monkeypatch.setattr(
        openai_compat.OpenAICompatProvider, "list_models", lambda self: list(LIVE_MODELS)
    )
    r = runner.invoke(
        app,
        ["chat", "hi", "--mock", "--provider", "nvidia", "--model", "z-ai/glm-5.2", "-q", "--no-stream"],
    )
    assert r.exit_code == 0, r.output
    db = _db(home)
    try:
        rows = db.query("SELECT agent, provider, model FROM turns WHERE agent='chat' ORDER BY seq")
        assert rows and rows[-1]["provider"] == "nvidia"
        assert rows[-1]["model"] == "z-ai/glm-5.2"
    finally:
        db.close()


def test_chat_override_requires_pair(home):
    r = runner.invoke(app, ["chat", "hi", "--mock", "--provider", "nvidia"])
    assert r.exit_code == 1
    assert "--provider and --model must be given together" in r.output
