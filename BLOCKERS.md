# BLOCKERS.md — reconcile/glm2 open-item tracker

Purpose: enumerate every outstanding blocker on `reconcile/glm2` so an external
reviewer (glm) can resolve them without re-deriving context from the diff. This
file ships on the branch so it is readable from the remote checkout.

## Where to find the repo

- Remote: `git@github.com:The-Despicable/Black.git`
- Branch: `reconcile/glm2` (pushed 2026-11-07; PR URL surfaced by GitHub on push)
- Base: `main` @ `db82201c`
- Head at authoring time: `f70f11fc`
- Working clone at author: `/home/yaser/live/Raphael_Black`
- All commits: `git log --oneline db82201c..HEAD`

## First commands on a fresh checkout

```bash
git clone git@github.com:The-Despicable/Black.git
cd Black
git checkout reconcile/glm2
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev,multiagent,c2,exploitation]'
.venv/bin/python -m pytest tests/ -q               # target: green
```

- Python at author: **3.14.4** (`.venv`). `pyproject.toml` has no
  `requires-python` — glm to set an explicit lower bound (#3).
- Without `pip install -e .`, the metadata-based `__version__` falls back
  to the hardcoded `3.1.0` (this fallback is tested in
  `tests/test_c2_hardening.py::TestVersionSingleSourcing`).

## Non-shipped artifacts (do NOT promote as code)

These are untracked on the author's machine and must not be pushed
accidentally. Either delete, `.gitignore`, or commit deliberately.

- `AUDIT_REPORT_2026-11-03.md` — preserved earlier audit; superseded by
  `AUDIT_REPORT.md`.
- `AUDIT_SUMMARY.md`, `COMPLETE_BRAIN_PROMPT.md`, `IMPLEMENTATION_CHECKLIST.md`,
  `REMEDIATION_COMMANDS.md`, `WEB_UI_IMPLEMENTATION_SPEC.md` — planning docs
  from the build phase.
- `audit/` — 7 historical audit drafts (`audit1.md`…`audit7.md`).
- `BUILD_*`, other stray planning files. Run the credential-pattern scan
  before any of these are tracked (some reference `/home/yaser/...` and run transcripts).

## Blockers

### B1 — Full suite verdict (GREEN)
**STATUS: GREEN — 253 passed / 0 failed** (run completed during authoring:
`.venv/bin/python -m pytest tests/ -q` → 253 passed, 27 warnings, 114.06s,
node 63754). Any failure glm observes must be treated as a regression
introduced after commit `f70f11fc`; diagnose **without** reverting the
import-path fixes (move the runtime path to `__file__`-relative or inject
under test fixtures instead).

### B2 — configs/judge_report.json (~260 frozen /home/yaser/… paths)
`scripts/JUDGE.py` writes to `ROOT/judge_report.json` (root = `scripts/`),
so `configs/judge_report.json` is a committed historical *snapshot* and is
not read at runtime. Decision needed: keep (label as snapshot), `.gitignore`, or
delete. Must be documented — currently noted in `AUDIT_REPORT.md` §2.6.
Do not silently make it a runtime file.

### B3 — cli / Python version metadata — RESOLVED
`requires-python = ">=3.10"` and `textual>=1.0,<9` in the `multiagent` extra
(1.0.0 floor and 8.2.8 both pass all 26 TUI tests on Python 3.12.16).
`pip install -e '.[dev,multiagent]'` succeeds on a clean venv and
`raphael-ma version` → `3.1.0`. `cloak_service` ships via the
`__init__.py` added in `a9161257`.

### B4 — NDJSON purity re-check (click >= 8.2)
`raphael-ma --json chat "..."` must emit **only** NDJSON to stdout; all
diagnostics (banner, phase rules) on stderr. The passing implementation is in
`tests/test_raphael_multiagent_chat.py::_separate_stream_runner`. Re-run:

```bash
.venv/bin/python -m pytest tests/test_raphael_multiagent_chat.py tests/test_run_screens.py -q
```

### B5 — Credential-pattern scan of the final diff
Run the standard credential-pattern scan over `git diff db82201c..HEAD`.
The single expected dependency-pin hit is one specific package line in the
requirement files (the key-store library pinned in three requirement files
and the `pyproject.toml` optional `c2` group). The name and version bound
are intentionally not spelled out in this tracker so that documentation
text never trips the fingerprint scan. glm can re-derive the exact package value
from `pyproject.toml` and the requirements files directly.

### B6 — AUDIT_REPORT.md currency
`AUDIT_REPORT.md` §2.6 amended for the extended portability work. If glm adds
any commit touching tracked code, append a row to the finding matrix. Module
version assertions live in `tests/test_c2_hardening.py`.

### B7 — Untracked artifact disposition (see §non-shipped)
Make explicit decisions for each file above; none may ship by accident.
Recommended: delete planning docs, gitignore `audit/`, keep `audit/` contents
as a reference directory under `.gitignore`.

### B8 — src/orchestrator/hrm_service.py does not exist
`configs/hrm_service.conf` is now labelled a template only (header comment).
Either implement the module or delete the conf. The module referenced by the
template is not in the tree; no consumer code references it. Minor.

## Subordinate findings discovered during reconciliation

- `pyproject.toml` does not install as a *namespace* package problem:
  `include = ["harness*", "harness.*", "cloak_service*", "raphael*", "raphael.*"]`
  with `where = ["src"]`; `src/cloak_service/__init__.py` was missing
  (fixed).
- `.gitignore` had an unanchored `arena/` rule which silently hid
  **8,745 tracked files** under `src/arena/`. Anchored to `/arena/`.
- `src/recon-pipeline/main.py` and `src/bridge/raphael_bridge.py` used
  `sys.path.insert(0, "/home/yaser/...")` and did not import on other
  machines (fixed).
- `tests/test_run_screens.py` is the Click>=8.2-aware version that must be
  kept (over the bundle's older `CliRunner(mix_stderr=False)` variant).
- `src/harness/black_hat_core.py`: `AntiForensicCleanup._secure_delete_sync`
  previously called `os.urandom(size)` allocating the whole file — chunked to
  64 KiB (fixed).
- `LogSuppressor.final_log_clear` keeps auditpol + bash-history clearing that
  the bundle version dropped — current (db82201c) preserved.
- Four previously documented "dangling root symlinks" (`cai_service`,
  `cloak_service`, `mcp_hub`, `mhddos_service`) were already removed in
  commit `db82201c`.

## Open-item audit matrix (originally 12 findings)

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| 1  | CRITICAL | Hardcoded credentials | Fixed (phase 1, `59d91b91`) |
| 2  | CRITICAL | Unauthenticated C2 server | Fixed (phase 1) |
| 3  | CRITICAL | `pickle`-based serialization | Fixed (phase 1) |
| 4  | CRITICAL | Shell/SQL/SSRF/path-traversal in CLI | Fixed (phase 1) |
| 5  | HIGH     | Anti-forensic ops claimed success | Fixed (§2.1) |
| 6  | HIGH     | Legacy C2 Fernet channel | Fixed (AEAD AES-256-GCM) |
| 7  | HIGH     | No rate limit; unbounded frames | Fixed (rate limiter + 16 MiB cap) |
| 8  | MEDIUM   | Services bound 0.0.0.0 by default | Fixed (loopback defaults) |
| 9  | MEDIUM   | Unpinned dependencies | Fixed (lower+upper bounds) |
| 10 | MEDIUM   | Author-machine paths | Fixed (§2.6 expanded) |
| 11 | LOW      | Version skew 0.3.0 vs 3.1.0 | Fixed (metadata-first) |
| 12 | LOW      | Collection errors blocked modules | Fixed (imports restored) |

## Key file map for glm

| Topic | Location |
|---|---|
| New operational audits | `AUDIT_REPORT.md`, this file |
| Bundle-vs-current reconciliation reference | `/home/yaser/live/glm/2/*-CHANGES.md` (local only), `/tmp/opencode/raphael-bundle` |
| Anti-forensic primitives | `src/harness/black_hat_core.py::{AntiForensicCleanup,LogSuppressor}` |
| C2 hardening (legacy) | `src/harness/rat_c2.py::AEADChannel, RateLimiter` |
| C2 hardening (secure) | `src/harness/rat_c2_secure.py::SecureC2Server` |
| Portability shims | `src/orchestrator/config/{paths,target}.py` |
| 11 arena portability fixes | `src/arena/d{7..16}_*.py` |
| Remaining portability fixes | `scripts/{d6b_runner,d6c_reconcile,phase0_audit,run_challenge000}.py`, `src/{recon-pipeline/main,bridge/raphael_bridge}.py`, `src/raphael/techniques/ad1_xor_sweep.py` |
| Version | `src/raphael/multiagent/__init__.py`, `pyproject.toml` |
| Tests for all of the above | `tests/test_anti_forensic_verification.py`, `tests/test_async_safety.py`, `tests/test_c2_hardening.py`, `tests/test_brain_tui.py`, `tests/test_run_screens.py`, `tests/test_raphael_multiagent_chat.py` |
| Setup guide | `RESTORATION.md` |

## Acceptance (from referee brief)

- Tests green, NDJSON pure, version 3.1.0, no credential-material
  committed, no `/home/yaser` paths in executable/imported Python, branch
  ready to merge.
- The only dependency-pin hit that may surface from this scan is the
  key-store package line in the requirement files (name omitted here to
  avoid a self-referential false positive; glm can re-derive from
  `pyproject.toml`).
- Untracked artifacts either deleted, gitignored, or tracked — none may ship.

Authored by BlackBuilder. All code shipped on the branch pushed 2026-11-07.
