# Compatibility Report — agora multi-agent CLI → Raphael Black Hat Harness v3.1

**Status:** read-only analysis (no repository modifications or builds were performed)
**Sources analyzed:**

- `C:\Users\yaser\live\message-9e4f8928-ea43-416e-87ae-44dc292b75e4\` (agora CLI, 23 Python files, v0.1.0)
- `C:\Users\yaser\live\Raphael_RedTeam\` (Raphael Black Hat Harness v3.1, pyproject + orchestrator/harness stacks)

**Goal:** determine what is required to build a new (or ported) CLI for Raphael using the agora implementation as the starting point.

---

## 1. Executive summary

agora is a small, well-structured Python CLI (`typer` + `rich` + `sqlite3` + OpenAI-compatible provider adapter). Its feature surface (multi-round debates, multi-agent communities, model teams, a self-evolving persona genome, memory/insights, transcripts, provider health checks) is a plausible foundation for a Raphael operator-facing shell.

However, it is **not drop-in compatible** with Raphael today. The blockers, in priority order, are:

1. **Stack mismatch** — agora depends on `typer` (not installed in the Raphael venv) and uses synchronous HTTP (`requests`), while Raphael's Python layer is async (`aiohttp`) and routed by model-prefix heuristics (`orchestrator/providers.py`).
2. **Governance gap** — agora executes LLM work without any link to Raphael's `UnifiedBroker`, `AuditSink`, or `EmergencyKillSwitch`. For a black-hat harness this is a fail-closed violation, not an ergonomic gap.
3. **Two tools share one name** — `pyproject.toml` installs a Python `raphael` entry point, while `src/cli` is an OpenClaude/JS CLI also named `raphael`. The new Python CLI must be namespaced to avoid an installer collision.
4. **No central data layer in Raphael** — agora's `BrainDB` schema is new functionality. Raphael keeps per-module `sqlite3` stores. The brain schema must be adopted deliberately and placed under Raphael's data/logging conventions.
5. **Naming/packaging** — agora assumes it is an installed package (`from .config import …`, `from ..brain.db import …`). It is currently only a flat directory of modules and will not import as-is.

agora's core design (config-as-dataclass, context-managed DB sessions, immutable mode resolution, secret masking, structured logging, allow-listed SQL wipes) is sound and should be retained.

---

## 2. Environment observations (verified)

| Capability | Raphael Python venv | agora requires |
|---|---|---|
| Python | `>=3.9` (NgModule uses `X \| Y` unions, i.e. 3.10+) | 3.10+ (f-strings, dataclasses OK) |
| `typer` | **missing** | required |
| `rich` | present | required |
| `pyyaml` | present (6.0.3) | required |
| `requests` | present (2.34.2) | required |
| `aiohttp` | present (3.14.3) | not used by agora |
| `fastapi` / `pydantic` | present | not used by agora |

**Operational finding while reading:** the reviewed agora snapshot compiles/runs now (community-mode crash was fixed in the delivered revision), but no Python CLI can be registered with Raphael today because `typer` is absent.

---

## 3. Module-by-module compatibility map

| agora module | Raphael equivalent / home | Fit | Notes |
|---|---|---|---|
| `config.py` (`Config`, `_mask_secrets`, `load_config`) | `orchestrator/providers.py` env constants + `.env` | Partial | Decide single source of truth. Either YAML extends env, or env file is generated from YAML. Masking + `with_mode` should be kept. |
| `paths.py` (`validate_home_path`) | `harness` has `logs/`, data dirs | New | Adopt as-is; validate against Raphael's data root. |
| `log.py` | `logging` is configured in `black_hat_cli.py` | New (better) | Replace `logging.basicConfig` with `configure_logging`. |
| `base.py` (`ChatMessage`, `Provider`, `DEFAULT_SCORE`) | `orchestrator/providers.py` (dict messages) | Partial | Bridge or port dataclass. `DEFAULT_SCORE` should live next to Raphael scoring if any. |
| `llm/openai_compat.py` | `orchestrator/providers.py` (`_call_*`, `call_model`) | Conflict | Two adapters; consolidate. Requests-based SSE vs aiohttp. Do not run both in production. |
| `llm/registry.py` | None equivalent | New | Reuse Raphael's `call_model` routing through a thin binding shim. |
| `llm/mock.py` | None (Raphael has no offline mock) | New asset | Keep; required for CI and dev. |
| `db.py` (`BrainDB`, schema, `wipe`) | Per-module `sqlite3` stores, no shared brain. | New schema | Adopt under `~/.raphael` or repo `data/`. |
| `memory.py` / `vectors.py` | No shared memory/vector layer | New | Evaluate against Raphael's `student/research_scheduler.py` and `blackboard.py` before duplicating. |
| `personas.py` / `brain/*` | `orchestrator/brain` (tactics, strategy) | Concept clash | Rename or integrate; avoid two "brain" packages. |
| `orchestrators/debate.py`, `community.py`, `teams.py` | No direct analog | New capability | Core value add. Gate behind governance checks. |
| `brain/evolver.py`, `reflector.py` | `orchestrator/student`, `capability_broker` | Partial overlap | De-duplicate metrics/state references. |
| `transcript.py` | `reports/` / session logs | New-ish | Align path and format; no conflict likely. |
| `ui.py` (`rich`) | argparse + print | Upgrade | Keep; add `NO_COLOR` verification (already supported by rich). |
| `cli.py` (`typer`) | `argparse` in `black_hat_cli.py` and `harness/cli.py` | Mismatch | Either add `typer` or rewrite commands with argparse. |
| `tests/test_cli_unit.py`, `test_smoke.py` | `tests/` with pytest | New | Port; update imports/packaging. |

---

## 4. What needs to be ADDED (Raphael does not have these yet)

1. **`typer` dependency** (or a complete argparse rewrite of the command tree).
2. **Brain storage schema** (`BrainDB` and its 8 tables) and its migration/seed flow, placed under Raphael's data conventions.
3. **Provider binding layer** that maps Raphael roles (e.g. `pro`, `judge`) to concrete provider/model pairs inside a config file.
4. **Mock provider** for offline development and CI.
5. **Transcript writer** with stable file naming/optional dir config.
6. **Semantic-ish memory search** (agora's vector cosine layer). Raphael has no shared embedding store; either reuse it or back it with an existing vector library.
7. **Evaluation loop tests** for the CLI command exit codes and governance failure paths.
8. **Shell completion / `--version` parity** (agora provides both; Raphael's CLI does not).
9. **Governance audit integration** — every command should emit an audit record through `AuditSink` and check `EmergencyKillSwitch`.
10. **Config command UX** (`raphael config`, masked by default) to replace scattered env-only inspection.

---

## 5. What needs to be FIXED (blockers before integration)

### 5.1 Package layout / imports

agora uses relative imports assuming it is a package:

- `from .config import Config`
- `from .llm.registry import Registry`
- `from ..brain.db import BrainDB`

There is no `setup.py`/`pyproject` for agora in the delivered bundle. To integrate, it must be placed under a real package inside Raphael, e.g. `src/raphael/multiagent/` or `src/harness/multiagent/`, and its relative imports validated.

**Acceptance:** `python -c "import raphael.multiagent.cli"` (or chosen namespace) works from repo root with `PYTHONPATH=src`.

### 5.2 Dependency/runtime split

- Add `typer` to Raphael's optional dependencies (e.g. `cli = ["typer>=0.12", "rich>=13.7"]`) or port to `argparse`.
- Confirm `rich` is importable in the Raphael environment (it is in the analyzed venv).
- Avoid shipping two competing CLIs named `raphael`. Recommend either:
  - **Python side:** expose as `raphael-harness` or `rh` command, or
  - **JS side:** wrap the Python harness through `bridge/raphael_bridge.py` (already present in `src/cli`) instead of duplicating entry points.

### 5.3 Provider consolidation

agora's adapter (`requests`, blocking, `stream_chat`) cannot coexist with Raphael's `call_model` routing without drift. Required fix:

- Make one adapter canonical. Recommendation: adapt agora to Raphael's async `orchestrator.providers.call_model`, whose routing already understands NVIDIA/Ollama/OpenAI prefixes and env-var-based keys.
- Preserve agora's two adapter behaviors worth keeping: SSE parsing, thinking-tag stripping (`strip_reasoning`), retries/backoff on 5xx, and non-retry on 4xx.
- Handle streaming through async generators and update orchestrators to `await` provider calls, or isolate CLI providers in a thread executor if keeping them synchronous.

### 5.4 Governance & safety

Raphael's existing CLI (`black_hat_cli.py`) wires an `AuditSink`, `UnifiedBroker`, and `EmergencyKillSwitch` for each command. The ported multi-agent CLI currently has no governance hook.

Required before shipping:

- Bootstrap the same trio at command start (`logs/harness_audit.jsonl` path is already the convention).
- Emit audit entries for debate/community/teams start/end and failures.
- Stop execution if the kill switch is engaged (checked before each round).
- Do not expose arbitrary file-write paths (transcript dirs, `--path`) without `validate_home_path`-style guards.
- Do not hard-code API keys (the Web UI currently has a hard-coded NVIDIA fallback for dev). For the CLI, keys must come only from env/config.

### 5.5 Data location & ownership

- Place `brain.db` under Raphael's existing data conventions (configurable home under `~/.raphael` or repo `data/`), not agora's `~/.agora`.
- Align transcript output dir with existing Raphael logging/reports (or keep configurable but default inside the project data tree).
- Avoid colliding with `src/orchestrator/brain`, `src/raphael/...`, and `src/raphael/circulatory/blackboard.py` naming. Rename module namespace to prevent confusion (recommend `raphael.multiagent.*`).

### 5.6 Async/Sync contract

agora's orchestrators are synchronous; Raphael's provider and model routing are async. Mixing without an explicit bridge will cause runtime errors or blocked event loops. Pick one contract and implement a single adapter boundary.

---

## 6. What needs to be REFINED (quality, performance, correctness)

1. **Secret handling** — agora's `_mask_secrets` is good. Extend it to nested role bindings and env-expanded values; ensure `agora config` equivalent never prints keys unless `--reveal`.
2. **CLI ergonomics** — add `--json` output mode to key commands for machine consumption (Raphael's current CLI mostly prints ad-hoc text or `json.dumps`).
3. **Concurrency** — set SQLite `busy_timeout` / WAL mode if multiple Raphael processes or team phases may touch `brain.db`.
4. **Observability** — replace broad exception handlers with logged warnings; agora's hardened revision already does this; keep and extend.
5. **Validation** — validate `community --agents` range (2–6) and `teams` YAML schema before execution.
6. **Provider health** — reuse Raphael's Ollama/NVIDIA prefixes for routing; avoid duplicating prefix heuristics.
7. **Memory/search** — benchmark the cosine loop; add an index or cap to insight count to avoid O(n) scanning at scale.
8. **Test coverage** — port the 17 in-process `CliRunner` tests (masking, path guards, pagination, non-quiet regression, `NO_COLOR`) into Raphael's pytest tree.
9. **Documentation** — add a "Diagnostics, Security, and Shell hygiene" section (as in agora's README) to Raphael docs.
10. **Branding** — rename `agora` app strings or consciously keep a multi-agent sub-tool identity (e.g. `raphael debate`), but keep user-facing help consistent with `Black Hat Harness`.

---

## 7. Proposed integration plan (read-only phases; no code changes yet)

| Phase | Work | Exit criteria |
|---|---|---|
| 0 | Package skeleton + dependency option | `import raphael.<cli>` succeeds; `typer` optional dep documented |
| 1 | Provider bridge | Single adapter uses Raphael `call_model`; streaming + thinking-tag stripping preserved |
| 2 | Governance wiring | Debate round checks kill switch; audit events written to `logs/harness_audit.jsonl` |
| 3 | Brain DB adoption | Schema colocated with Raphael data; `init`/`brain reset` functional |
| 4 | Command surface | `debate`, `community`, `teams`, `brain`, `providers`, `evolve`, `config`, `version` exposed |
| 5 | Tests & hardening | CliRunner + smoke tests green; non-quiet community regression test passing |
| 6 | Release decision | Disambiguate Python vs JS `raphael` binaries; update pyproject entry point |

---

## 8. Risks if integrated without the fixes above

- **Fail-closed violation:** an operator-facing CLI that runs models outside governance undermines Raphael's core claim. The broker must be wired before any port ships.
- **Silent crashes:** agora had hidden `NameError`/`UnboundLocalError` in community mode that only appeared when the UI (rich) and non-quiet paths executed. Keep the regression tests in Phase 5.
- **Secret exposure:** without masked config output, provider keys can leak into transcripts/logs.
- **Installer collision:** two packages named `raphael` (Python + JS) will cause packaging/install confusion.

---

## 9. Verification checklist (for when implementation begins)

```text
# from repo root, after Phase 0
PYTHONPATH=src python -c "import raphael.<cli_namespace>"
pytest tests/test_cli_unit.py -q
pytest tests/test_smoke.py -q
raphael config              # secrets masked
raphael config --reveal     # secrets visible
raphael init --path /      # must be rejected
raphael community "topic"  # non-quiet mode must not crash
raphael --verbose debate "motion" --rounds 1
```

---

## 10. Bottom line

**Add:** typer (or argparse port), brain schema, memory/search, mock provider, transcript writer, governance hooks, CLI tests.
**Fix:** package imports, provider consolidation (async vs sync), governance wiring, CLI binary collision, data-path placement, async contract.
**Refine:** secret masking depth, JSON output mode, SQLite concurrency, UI consistency, vector performance, documentation, branding.

The agora code is a viable starting point, but only if the provider and governance layers are reconciled with Raphael's existing async, fail-closed architecture. Do not ship the port until Phase 2 and Phase 5 above are complete.
