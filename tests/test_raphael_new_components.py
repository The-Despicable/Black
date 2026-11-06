"""Tests for new raphael-ma components: UnrestrictedGovernance, benchmark, brain import."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from raphael.multiagent.cli import app
from raphael.multiagent.governance import (
    UnrestrictedGovernance,
    build_governance,
    get_governance,
)

runner = CliRunner()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RAPHAEL_MA_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "home"


# ------------------------------------------------------------------ governance
def test_unrestricted_never_blocks(tmp_path):
    audit = tmp_path / "audit.jsonl"
    gov = UnrestrictedGovernance(audit_path=str(audit))

    for i in range(50):
        assert gov.check(f"action_{i}", {"data": "x" * 500}) is True

    gov.audit({"event": "test_event", "value": 42})

    assert audit.exists()
    lines = audit.read_text().strip().split("\n")
    assert len(lines) == 51  # 50 checks + 1 audit


def test_unrestricted_context_manager(tmp_path):
    audit = tmp_path / "audit.jsonl"
    with UnrestrictedGovernance(audit_path=str(audit), session_tag="test-tag") as gov:
        gov.check("test", {"key": "value"})
        stats = gov.get_stats()
        assert stats["mode"] == "unrestricted"
        assert stats["session_tag"] == "test-tag"
        assert stats["checks_performed"] == 1


def test_build_governance_unrestricted():
    gov = build_governance({"governance": {"type": "unrestricted", "audit_path": "/tmp/x.jsonl"}})
    assert isinstance(gov, UnrestrictedGovernance)


def test_build_governance_null():
    gov = build_governance({"governance": {"type": "null"}})
    from raphael.multiagent.governance import NullGovernance

    assert isinstance(gov, NullGovernance)


def test_build_governance_audit(tmp_path):
    gov = build_governance({"governance": {"type": "audit", "audit_path": str(tmp_path / "a.jsonl")}})
    from raphael.multiagent.governance import FileAuditGovernance

    assert isinstance(gov, FileAuditGovernance)


def test_build_governance_unknown():
    with pytest.raises(ValueError):
        build_governance({"governance": {"type": "bogus"}})


# ------------------------------------------------------------------ CLI governance
def test_governance_status(home):
    assert runner.invoke(app, ["init"]).exit_code == 0
    r = runner.invoke(app, ["governance", "status"])
    assert r.exit_code == 0, r.output
    assert "Governance" in r.output


def test_governance_unrestricted(home, tmp_path):
    assert runner.invoke(app, ["init"]).exit_code == 0
    audit = tmp_path / "redteam.jsonl"
    r = runner.invoke(
        app,
        ["governance", "unrestricted", "--enable", "--audit-path", str(audit), "--session-tag", "t1"],
    )
    assert r.exit_code == 0, r.output
    assert "UNRESTRICTED MODE" in r.output


# ------------------------------------------------------------------ CLI benchmark
def test_benchmark_providers(home):
    assert runner.invoke(app, ["init"]).exit_code == 0
    r = runner.invoke(app, ["benchmark", "providers"])
    assert r.exit_code == 0, r.output
    assert "nvidia" in r.output


def test_benchmark_run_mock(home):
    assert runner.invoke(app, ["init"]).exit_code == 0
    r = runner.invoke(
        app, ["benchmark", "run", "test", "--providers", "mock", "--rounds", "1"]
    )
    assert r.exit_code == 0, r.output
    assert "mock" in r.output


# ------------------------------------------------------------------ CLI brain import
def test_brain_import(home, tmp_path):
    assert runner.invoke(app, ["init"]).exit_code == 0

    import_file = tmp_path / "session.json"
    import_file.write_text(
        json.dumps(
            {
                "session_id": "imported-test-001",
                "kind": "debate",
                "topic": "imported topic",
                "mode": "mock",
                "started_at": "2026-10-31T12:00:00",
                "turns": [
                    {
                        "agent": "PRO",
                        "role": "pro",
                        "phase": "debate",
                        "round": 1,
                        "provider": "mock",
                        "model": "mock-default",
                        "content": "imported turn content",
                        "latency_ms": 50.0,
                        "ok": 1,
                    }
                ],
                "insights": [{"text": "imported insight", "confidence": 0.9}],
            }
        )
    )

    r = runner.invoke(app, ["brain", "import", str(import_file)])
    assert r.exit_code == 0, r.output
    assert "imported session" in r.output

    r = runner.invoke(app, ["brain", "sessions"])
    assert r.exit_code == 0
    assert "imported topic" in r.output
