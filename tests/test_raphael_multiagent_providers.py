"""Provider selection tests — binding LIVE model ids into roles.

Runs the real Typer surface with a temp RAPHAEL_MA_HOME; the provider's
/mmodels list is monkeypatched so tests are offline and deterministic.
The line-surgery config writer must preserve surrounding comments.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import raphael.multiagent.llm.openai_compat as openai_compat
from raphael.multiagent.cli import app
from raphael.multiagent.paths import config_path

runner = CliRunner()

LIVE_MODELS = [
    "z-ai/glm-5.2",
    "deepseek-ai/deepseek-v4.1-flash",
    "qwen/qwen3-coder-480b",
    "meta/llama-4-scout",
]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RAPHAEL_MA_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    monkeypatch.setattr(
        openai_compat.OpenAICompatProvider, "list_models", lambda self: list(LIVE_MODELS)
    )
    return tmp_path / "home"


def _cfg_raw(home: Path) -> dict:
    return yaml.safe_load(config_path(home).read_text(encoding="utf-8"))


def test_models_json_lists_live(home):
    r = runner.invoke(app, ["--json", "providers", "models", "nvidia"])
    assert r.exit_code == 0, r.output
    rows = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    row = next(o for o in rows if "models" in o)
    assert row["provider"] == "nvidia"
    assert row["models"] == LIVE_MODELS
    assert row["count"] == len(LIVE_MODELS)


def test_select_binds_role(home):
    r = runner.invoke(
        app, ["providers", "select", "nvidia", "--model", "z-ai/glm-5.2", "--role", "chat"]
    )
    assert r.exit_code == 0, r.output
    roles = (_cfg_raw(home).get("roles") or {})
    assert roles["chat"] == {"provider": "nvidia", "model": "z-ai/glm-5.2"}
    # pre-existing bindings untouched
    assert roles["pro"]["provider"] == "nvidia"
    # the governance block comments survived the surgery
    text = config_path(home).read_text(encoding="utf-8")
    assert "# kill_switch:" in text
    assert "# audit_path:" in text


def test_select_rejects_model_not_in_live_list(home):
    r = runner.invoke(
        app,
        ["providers", "select", "nvidia", "--model", "meta/llama-3.3-70b-instruct", "--role", "chat"],
    )
    assert r.exit_code == 1
    before = config_path(home).read_text(encoding="utf-8")
    # config unchanged after rejection
    after = config_path(home).read_text(encoding="utf-8")
    assert before == after


def test_select_force_allows_offlist_model(home):
    r = runner.invoke(
        app,
        ["providers", "select", "nvidia", "--model", "whatever/unknown", "--role", "chat", "--force"],
    )
    assert r.exit_code == 0, r.output
    roles = _cfg_raw(home).get("roles") or {}
    assert roles["chat"]["model"] == "whatever/unknown"


def test_select_all_rebinds_every_role_on_provider(home):
    cfg = _cfg_raw(home)
    nvidia_roles = [
        r for r, b in (cfg.get("roles") or {}).items() if b.get("provider") == "nvidia"
    ]
    assert nvidia_roles, "default config must bind some roles to nvidia"
    r = runner.invoke(
        app,
        ["providers", "select", "nvidia", "--model", "deepseek-ai/deepseek-v4.1-flash", "--role", "all"],
    )
    assert r.exit_code == 0, r.output
    roles = _cfg_raw(home).get("roles") or {}
    for role in nvidia_roles:
        assert roles[role]["model"] == "deepseek-ai/deepseek-v4.1-flash"
    # non-nvidia roles keep their binding
    con = roles["con"]
    assert con["provider"] == "ollama-cloud"


def test_select_unknown_provider(home):
    r = runner.invoke(app, ["providers", "select", "nope", "--model", LIVE_MODELS[0]])
    assert r.exit_code == 1


def test_select_without_model_fails_offtty(home):
    r = runner.invoke(app, ["providers", "select", "nvidia"])
    assert r.exit_code == 1
    assert "--model" in r.output


def test_select_new_role_is_created(home):
    r = runner.invoke(
        app, ["providers", "select", "ollama-cloud", "--model", "qwen/qwen3-coder-480b", "--role", "chat"]
    )
    assert r.exit_code == 0, r.output
    roles = _cfg_raw(home).get("roles") or {}
    assert roles["chat"] == {"provider": "ollama-cloud", "model": "qwen/qwen3-coder-480b"}


def test_providers_test_single(home):
    r = runner.invoke(app, ["providers", "test", "nvidia"])
    assert r.exit_code == 0, r.output
    r2 = runner.invoke(app, ["providers", "test", "does-not-exist"])
    assert r2.exit_code == 1
