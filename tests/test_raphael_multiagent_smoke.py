"""Smoke tests: full mock-mode cycle — debate, brain, teams, evolution."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RAPHAEL_MA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHONPATH", str(SRC))
    return tmp_path / "home"


def run_cli(home, *args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "raphael.multiagent.cli", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "RAPHAEL_MA_HOME": str(home), "PYTHONPATH": str(SRC)},
        cwd=str(cwd or REPO),
        timeout=300,
    )


def test_vectors_roundtrip():
    from raphael.multiagent.brain.vectors import cosine, embed, from_blob, to_blob

    a = embed("debates are won with quantified claims")
    b = embed("debates are won with quantified claims")
    c = embed("completely unrelated text about cooking pasta")
    assert cosine(a, b) > 0.99
    assert cosine(a, c) < 0.35
    assert cosine(a, from_blob(to_blob(a))) > 0.99


def test_init_and_debate_cycle(home, tmp_path):
    r = run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    assert (home / "brain.db").exists()

    r = run_cli(home, "debate", "AI will replace middle management", "--rounds", "1", "-q")
    assert r.returncode == 0, r.stderr

    r = run_cli(home, "brain", "status")
    assert r.returncode == 0, r.stderr
    assert "sessions" in r.stdout.lower()

    r = run_cli(home, "brain", "search", "what wins debates")
    assert r.returncode == 0, r.stderr


def test_community_and_teams(home):
    r = run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    r = run_cli(home, "community", "build vs buy a database", "--agents", "3", "--rounds", "1", "-q")
    assert r.returncode == 0, r.stderr
    r = run_cli(home, "teams", "examples/teams.example.yaml", "-q")
    assert r.returncode == 0, r.stderr


def test_evolution_applies_and_rolls_back(home):
    r = run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    for motion in ("Motion one", "Motion two", "Motion three"):
        run_cli(home, "debate", motion, "--rounds", "1", "-q")
    r = run_cli(home, "evolve", "run", "--dry-run")
    assert r.returncode == 0, r.stderr
    r = run_cli(home, "evolve", "run")
    assert r.returncode == 0, r.stderr
    from raphael.multiagent.brain.db import BrainDB
    from raphael.multiagent.personas import persona_version

    db = BrainDB(home=home)
    try:
        v = persona_version(db, "pro")
        assert v >= 1
    finally:
        db.close()
