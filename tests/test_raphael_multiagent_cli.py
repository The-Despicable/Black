"""Unit tests via typer.testing.CliRunner (fast, in-process).

Complements tests/test_smoke.py (subprocess integration): here we pin the
hardened CLI surface — resource handling, secret masking, path validation,
error codes, NO_COLOR, and the non-quiet regression for community mode.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from raphael.multiagent.cli import app

runner = CliRunner()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RAPHAEL_MA_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)  # transcripts/ and caches land in tmp
    return tmp_path / "home"


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert "raphael-ma" in r.output


def test_init_creates_home(home):
    r = runner.invoke(app, ["init"])
    assert r.exit_code == 0, r.output
    assert (home / "brain.db").exists()
    assert (home / "config.yaml").exists()


def test_init_rejects_root_path(home):
    r = runner.invoke(app, ["init", "--path", "/"])
    assert r.exit_code == 1
    assert "invalid --path" in r.output


def test_init_rejects_file_path(home, tmp_path):
    victim = tmp_path / "not-a-dir"
    victim.write_text("i am a file")
    r = runner.invoke(app, ["init", "--path", str(victim)])
    assert r.exit_code == 1
    assert "not a directory" in r.output


def test_brain_subcommands_after_init(home):
    assert runner.invoke(app, ["init"]).exit_code == 0
    for args in (
        ["brain", "status"],
        ["brain", "insights"],
        ["brain", "sessions"],
        ["brain", "log"],
        ["brain", "search", "anything"],
        ["evolve", "stats"],
        ["providers", "list"],
    ):
        r = runner.invoke(app, args)
        assert r.exit_code == 0, f"{args}: {r.output}"


def test_debate_mock_smoke(home):
    assert runner.invoke(app, ["init"]).exit_code == 0
    r = runner.invoke(app, ["debate", "cats make better engineers", "--rounds", "1", "-q", "--no-stream"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["brain", "sessions"])
    assert r.exit_code == 0
    assert "cats" in r.output
    r = runner.invoke(app, ["brain", "log", "--last", "5"])
    assert r.exit_code == 0


def test_debate_and_community_non_quiet_regression(home):
    """Non-quiet mode once crashed: community.py used `console` unimported and
    joined a Rich Text object. These invocations pin the fix."""
    assert runner.invoke(app, ["init"]).exit_code == 0
    r = runner.invoke(app, ["debate", "motion alpha", "--rounds", "1", "--no-stream"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(
        app, ["community", "topic beta", "--agents", "3", "--rounds", "1", "--no-stream"]
    )
    assert r.exit_code == 0, r.output
    assert "MODERATOR SYNTHESIS" in r.output


def test_config_masks_inline_secrets(home):
    import yaml

    assert runner.invoke(app, ["init"]).exit_code == 0
    cfg_file = home / "config.yaml"
    data = yaml.safe_load(cfg_file.read_text())
    data["providers"]["nvidia"]["api_key"] = "sk-super-secret-nvidia-123"  # inline secret
    cfg_file.write_text(yaml.safe_dump(data, sort_keys=False))

    r = runner.invoke(app, ["config"])
    assert r.exit_code == 0
    assert "sk-super-secret-nvidia-123" not in r.output
    assert "***" in r.output
    # env var NAMES stay visible (they are not secrets)
    assert "NVIDIA_API_KEY" in r.output

    r = runner.invoke(app, ["config", "--reveal"])
    assert r.exit_code == 0
    assert "sk-super-secret-nvidia-123" in r.output


def test_teams_missing_file_exit_code(home):
    r = runner.invoke(app, ["teams", str(home / "nope.yaml")])
    assert r.exit_code == 1
    assert "not found" in r.output


def test_brain_reset_requires_confirmation(home):
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["debate", "a motion", "--rounds", "1", "-q", "--no-stream"]).exit_code == 0
    r = runner.invoke(app, ["brain", "sessions"])
    assert "a motion" in r.output

    r = runner.invoke(app, ["brain", "reset"])  # without --yes: refuses
    assert "Re-run with --yes" in r.output
    r = runner.invoke(app, ["brain", "sessions"])
    assert "a motion" in r.output  # memory intact

    r = runner.invoke(app, ["brain", "reset", "--yes"])
    assert r.exit_code == 0
    r = runner.invoke(app, ["brain", "sessions"])
    assert "a motion" not in r.output  # wiped


def test_resolve_mode_does_not_mutate_config():
    from raphael.multiagent.config import load_config

    cfg = load_config()
    before = cfg.raw.get("mode")
    from raphael.multiagent.cli import _resolve_mode

    _resolve_mode(cfg, live=True, mock=False)
    assert cfg.raw.get("mode") == before  # untouched

    pinned = _resolve_mode(cfg, live=True, mock=False)
    assert pinned.mode == "live"
    assert cfg.mode == before  # original still unchanged

    both = _resolve_mode(cfg, live=True, mock=True)
    assert both is cfg  # conflicting flags are ignored, no copy made


def test_session_pagination_offset(home):
    assert runner.invoke(app, ["init"]).exit_code == 0
    for m in ("motion one", "motion two", "motion three"):
        assert runner.invoke(app, ["debate", m, "--rounds", "1", "-q", "--no-stream"]).exit_code == 0
    r = runner.invoke(app, ["brain", "sessions", "--limit", "2"])
    assert r.exit_code == 0
    assert "motion three" in r.output and "motion two" in r.output
    assert "motion one" not in r.output
    r = runner.invoke(app, ["brain", "sessions", "--limit", "2", "--offset", "2"])
    assert r.exit_code == 0
    assert "motion one" in r.output


def test_wipe_allowlist_guard():
    from raphael.multiagent.brain.db import WIPEABLE_TABLES

    assert WIPEABLE_TABLES == frozenset({"sessions", "turns", "insights", "outcomes", "evolutions"})
    assert all(t.isidentifier() for t in WIPEABLE_TABLES)


def test_mask_secrets_unit():
    from raphael.multiagent.config import _mask_secrets

    raw = {
        "providers": {
            "nvidia": {
                "base_url": "https://x/v1",
                "api_key_env": "NVIDIA_API_KEY",   # name -> visible
                "api_key": "sk-live-abc",          # secret -> masked
            }
        },
        "auth_token": "tok-1",
        "PASSWORD": "hunter2",
        "models": ["a", "b"],
    }
    m = _mask_secrets(raw)
    assert m["providers"]["nvidia"]["api_key_env"] == "NVIDIA_API_KEY"
    assert m["providers"]["nvidia"]["api_key"] == "***"
    assert m["auth_token"] == "***"
    assert m["PASSWORD"] == "***"
    assert m["models"] == ["a", "b"]
    assert raw["providers"]["nvidia"]["api_key"] == "sk-live-abc"  # original untouched


def test_validate_home_path_unit(tmp_path):
    from raphael.multiagent.paths import validate_home_path
    from pathlib import Path

    good = validate_home_path(tmp_path / "agora-home")
    assert good.is_absolute() and good.name == "agora-home"
    with pytest.raises(ValueError):
        validate_home_path(Path("/"))
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(ValueError):
        validate_home_path(f)


def test_extract_json_never_raises():
    from raphael.multiagent.ui import extract_json

    assert extract_json("no json here") is None
    assert extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert extract_json('prefix {"b": [1,2]} suffix') == {"b": [1, 2]}
    assert extract_json("```json\n{broken\n```") is None  # fenced fallback
    assert extract_json("{also broken") is None


def test_no_color_env_disables_ansi():
    """NO_COLOR must strip ANSI escapes end-to-end (Rich honors it natively)."""
    import os

    repo = Path(__file__).resolve().parent.parent
    env = dict(os.environ, NO_COLOR="1", PYTHONPATH=str(repo / "src"))
    proc = subprocess.run(
        [sys.executable, "-m", "raphael.multiagent.cli", "version"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "\x1b[" not in proc.stdout
    assert "raphael-ma" in proc.stdout
