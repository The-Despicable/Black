# Raphael Multi-Agent CLI (ported module)

The `raphael/multiagent` package is the offline multi-agent debate/community/team shell
ported from the `agora` project. It is installed as an **optional** dependency and does
not change Raphael's attack surfaces or governance model.

## Install (development)

```bash
cd /home/yaser/live/Raphael_RedTeam
python3 -m pip install -e ".[multiagent]"   # or: apt install python3-typer
```

## Environment variables

- `RAPHAEL_MA_HOME` — home directory (default `~/.raphael/ma`)
- `RAPHAEL_MA_LOG` — log level (`debug`, `info`, `warning`, `error`)

## Run

```bash
PYTHONPATH=src RAPHAEL_MA_HOME=/tmp/ma-home python3 -m raphael.multiagent.cli init
PYTHONPATH=src RAPHAEL_MA_HOME=/tmp/ma-home python3 -m raphael.multiagent.cli debate "motion" --rounds 1
PYTHONPATH=src RAPHAEL_MA_HOME=/tmp/ma-home python3 -m raphael.multiagent.cli community "topic" --agents 3 --rounds 1
PYTHONPATH=src RAPHAEL_MA_HOME=/tmp/ma-home python3 -m raphael.multiagent.cli --json brain sessions
```

## Governance model (fail-closed)

Every session is initiated from `SessionRunner`, which loads `governance` config
(`audit_path`, `kill_switch`, `strict`). The Orchestrator calls `runner.gate(...)`
before every debate/community round, team phase, integration step, and before
`evolve run`. An engaged kill switch aborts with exit code 3 and writes
`session_aborted`.

The deployed-config strict default means that an empty `governance` section
raises at construction unless `strict: false` is set explicitly. For development
the generated config enables standalone allow-mode; do not carry that config into
authorized operation.

Configure authorized deployments as:

```yaml
governance:
  audit_path: "logs/harness_audit.jsonl"
  kill_switch: "your.module:callable"
  strict: true
```

`NullGovernance` is the dev/standalone fallback and is not a safe default for
production operation. Personnel must treat governance as `strict: true` whenever
an operator chain is present.

## Sync verification

- `PYTHONPATH=src python -c "import raphael.multiagent.cli"` (no left-over `agora` references)
- `pytest` in the `agora` source variant passed (53 tests) using `typer>=0.9`.

## Phase 1: governed host-provider wiring

Wire Raphael's canonical async provider into the Registry *without* bypassing
the multi-agent shell's governance. `build_registry` keeps the gateway seam
optional and only uses the host router when the package is live *and* the host
router can be imported; otherwise it falls back to agora's default adapter and
still enforces kill-switch/audit gates.

```python
from raphael.multiagent.config import load_config
from raphael.multiagent.harness_provider import build_registry

cfg = load_config()
cfg = cfg.with_mode("live")
registry = build_registry(cfg, use_raphael_router=True)
```

The adapter calls `orchestrator.providers.call_model` for each LLM slot and keeps
prompt/resolver routing in one place. Per-slot failures are still surfaced through
`runner.run_turn` with `gov.audit({"event": "turn_failed", ...})`.

## What was intentionally not added

- No "unrestricted" or authority-bypassing persona. All personas run through the
  same `SessionRunner` governance gating; kill-switch and audit behavior apply
  identically regardless of persona.
- No audit `"tool"` value normalization was introduced; the upstream
  `"tool": "agora"` remains and should be reconciled if you merge into the same
  JSONL files as the main harness.
