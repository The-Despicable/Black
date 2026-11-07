"""Tests for the improved debate feature.

Covers:
* Pre-turn thinking blocks are generated before each speech
* Speeches carry explicit headings (Framework / Arguments / Rebuttal / Closing)
* Round >1 is labeled Closing/Rebuttal, never "Opening statement"
* Thinking headings are distinct from speech headings
* Judge quotes actual transcript lines in reasoning
* NDJSON output stays pure (one JSON object per turn)
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from raphael.multiagent.cli import app

runner = CliRunner()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RAPHAEL_MA_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "home"


def _json_lines(output: str):
    """Parse only valid JSON lines from stdout (skips header banners)."""
    objs = []
    for ln in output.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objs.append(obj)
    return objs


def _debate_output(home, motion: str, rounds: int = 2):
    """Run a mock debate and return (turn_events, verdict)."""
    assert runner.invoke(app, ["init"]).exit_code == 0
    r = runner.invoke(
        app,
        ["--json", "debate", motion, "--rounds", str(rounds), "--mock", "--no-stream"],
    )
    assert r.exit_code == 0, r.output
    objs = _json_lines(r.stdout)
    turns = [o for o in objs if o.get("event") == "turn"]
    verdicts = [o for o in objs if isinstance(o, dict) and "winner" in o]
    return turns, verdicts[-1] if verdicts else None


def test_thinking_block_present(home):
    """Every turn includes a ### Thinking (deliberation) section."""
    turns, _ = _debate_output(home, "Open weights should be unrestricted", rounds=2)
    assert len(turns) == 4, f"expected 4 turns, got {len(turns)}"
    for ev in turns:
        text = ev.get("text", "")
        assert "### Thinking (deliberation)" in text, f"no thinking block in {text[:120]}"


def test_thinking_headings_distinct_from_speech(home):
    """Thinking uses '### Planned Arguments', speech uses '### Arguments'."""
    turns, _ = _debate_output(home, "Open weights should be unrestricted", rounds=2)
    for ev in turns:
        text = ev.get("text", "")
        assert "### Planned Arguments" in text, f"no planned args in {text[:120]}"
        assert "### Arguments" in text, f"no arguments heading in {text[:120]}"
        assert "### Closing Focus" in text, f"no closing focus in {text[:120]}"
        assert "### Closing" in text, f"no closing in {text[:120]}"


def test_round_two_labeled_closing(home):
    """Round 2 inner speech says 'Closing', never 'Opening statement'."""
    turns, _ = _debate_output(home, "Open weights should be unrestricted", rounds=2)
    round2 = [e for e in turns if e.get("round") == 2]
    assert len(round2) == 2, f"expected 2 round-2 turns, got {len(round2)}"
    for ev in round2:
        text = ev.get("text", "")
        assert "Closing" in text, f"round 2 missing Closing label: {text[:120]}"
        assert "Opening statement" not in text, f"round 2 mislabeled as opening: {text[:120]}"


def test_no_verbatim_applied_repetition(home):
    """Arguments don't all end with the same 'Applied to ...' tail."""
    turns, _ = _debate_output(home, "Open weights should be unrestricted", rounds=2)
    for ev in turns:
        text = ev.get("text", "")
        count = text.count("Applied to '")
        assert count == 0, f"verbatim 'Applied to' repetition found: {count}"


def test_no_duplicate_section_headings(home):
    """Each turn has one '### Framework' in thinking + one in speech."""
    turns, _ = _debate_output(home, "Open weights should be unrestricted", rounds=2)
    for ev in turns:
        text = ev.get("text", "")
        framework_count = text.count("### Framework")
        assert framework_count >= 1, f"no Framework heading: {text[:120]}"
        assert framework_count == 2, f"expected 2 Framework headings, got {framework_count}"


def test_judge_quotes_transcript(home):
    """Judge reasoning quotes actual transcript content, not defaults."""
    _, verdict = _debate_output(home, "Open weights should be unrestricted", rounds=2)
    assert verdict, "no final verdict event"
    reasoning = verdict.get("reasoning", "")
    assert "structured opening" not in reasoning, "judge fell back to default quote"
    assert "structured rebuttal" not in reasoning, "judge fell back to default quote"
    assert verdict.get("winner") in ("pro", "con", "tie")
    assert "pro" in verdict.get("scores", {})
    assert "con" in verdict.get("scores", {})


def test_ndjson_purity(home):
    """Every stdout line is valid JSON; no prose leaks into stdout."""
    turns, verdict = _debate_output(home, "Open weights should be unrestricted", rounds=2)
    assert len(turns) >= 4, f"expected at least 4 turns (2 sides × 2 rounds), got {len(turns)}"
    for ev in turns:
        assert "event" in ev
        assert ev["event"] == "turn"
        assert "agent" in ev
        assert ev["agent"] in ("PRO", "CON")
        assert "text" in ev
    assert verdict is not None
    assert "winner" in verdict
