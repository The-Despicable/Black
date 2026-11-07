# Security Audit & Remediation Report — Raphael_Black

**Repository:** `raphael-black` (v3.1.0) · **Audit scope:** tool's own infrastructure
(`src/harness/`, `src/agent/`, `src/orchestrator/config/`, `src/raphael/multiagent/`,
build & dependency metadata) · **Method:** static review + executable verification
(pytest suite, live socket smoke tests)

This report consolidates the remediation work across all phases. Phase 1
(criticals) landed in commit `59d91b91`; phases 2–4 (high/medium/low) are the
follow-ups tracked here. Every fix is backed by a test or a verified command —
no optimistic-success claims, mirroring the standard applied to the tool's own
runtime behavior.

---

## 1. Findings and status

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| 1 | CRITICAL | Hardcoded credentials (`master_key`, encryption keys) | **Fixed** (phase 1, `59d91b91`) — keys from env/config only |
| 2 | CRITICAL | Unauthenticated C2 server | **Fixed** (phase 1) — `rat_c2_secure.py`: mTLS + challenge-response |
| 3 | CRITICAL | `pickle`-based serialization | **Fixed** (phase 1) — JSON everywhere |
| 4 | CRITICAL | Shell / SQL / SSRF / path-traversal injection in CLI inputs | **Fixed** (phase 1) — validation + parameterized queries |
| 5 | HIGH | Anti-forensic ops claimed success without verification | **Fixed** — see §2.1 |
| 6 | HIGH | Legacy C2 channel used Fernet (AES-128-CBC+HMAC) | **Fixed** — see §2.2 |
| 7 | HIGH | No rate limiting on legacy C2; unbounded frame size | **Fixed** — see §2.3 |
| 8 | MEDIUM | Services bound `0.0.0.0` by default | **Fixed** — see §2.4 |
| 9 | MEDIUM | Unpinned dependencies | **Fixed** — see §2.5 |
| 10 | MEDIUM | Author-machine absolute paths (`/home/yaser/raphael-2.0`) | **Fixed** — see §2.6 |
| 11 | LOW | Version skew (`raphael-ma` reported 0.3.0 vs package 3.1.0) | **Fixed** — see §2.7 |
| 12 | LOW | Collection errors (`NameError: Tuple/Evidence`) blocked 8 test modules | **Fixed** — missing imports restored |

### Intentionally out of scope

The following are **by-design behaviors of the offensive tooling**, not
vulnerabilities of the tool itself, and were deliberately left untouched:

- Payload content containing `eval(`/`exec(` (PHP/JSP/polyglot webshell
  templates, pickle payload factory) — that is the product's purpose.
- `CERT_NONE` / `verify=False` in target-facing scanners, egress and C2
  implant transport — standard pentest posture against self-signed target
  certificates; opsec-relevant, not a tool defect.
- Wide binds on engagement listeners (reverse-shell catchers, evilginx,
  beacon) where the remote target must reach the listener.

## 2. Remediation detail (phases 2–4)

### 2.1 Verified anti-forensic primitives (`src/harness/black_hat_core.py`)

`AntiForensicCleanup` and `LogSuppressor` previously called methods that did
not exist (`_secure_delete`, `_timestomp`, `_wipe_free_space_*`,
`final_log_clear`) — every invocation raised and was swallowed. They now
exist with verified semantics:

- **`secure_delete_artifacts(paths, passes=3)`** — random overwrite →
  `fsync` → truncate → `fsync` → unlink → existence check. A path is
  reported `deleted` only if it is verifiably gone; nonexistent/invalid
  paths land in `failed` and are never touched. Symlinks and
  traversal-containing paths are rejected.
- **`timestomp_files(reference, paths=None)`** — a missing reference file is
  a **hard failure** (stamping against an unknown time would silently
  produce wrong timestamps). Applied stamps are re-`stat`ed and compared
  nanosecond-exact against the reference.
- **`wipe_free_space()`** — Linux reports `not_implemented` (no verified
  userspace primitive; honest instead of fake success). Windows attempts
  `cipher /w:` with a verified exit code.
- **`LogSuppressor.final_log_clear()`** — per-target `logs_cleared` /
  `failed`; non-root Linux returns `skipped` with the reason rather than
  pretending system logs were cleared.

Verified by: `tests/test_anti_forensic_verification.py` (7),
`tests/test_async_safety.py` (10).

### 2.2 AEAD channel crypto (`src/harness/rat_c2.py`)

The legacy `RATC2Server`/`RATClient` channel moved from Fernet to
**AES-256-GCM** via a new `AEADChannel`:

- Wire format per message: 12-byte random nonce ‖ ciphertext+tag.
- Any key material (raw 32-byte, str, former Fernet key) is derived to a
  32-byte AES key with SHA-256, so existing deployments keep working.
- Tampered or foreign-key ciphertext raises (`InvalidTag`) instead of
  yielding garbage.
- `rat_c2_secure.py` (the recommended path) already used AESGCM with mTLS;
  the legacy path no longer lags behind it.

Verified by: `tests/test_c2_hardening.py::TestAEADChannel` (6) and a live
beacon→ack socket exchange (`TestC2ChannelEndToEnd`).

### 2.3 Rate limiting & frame bounds (`src/harness/rat_c2.py`)

- **`ConnectionRateLimiter`** — per-IP sliding window (default 10 new
  connections/min/IP) plus a global concurrency cap (default 64), enforced
  in the accept loop; over-limit peers are closed immediately.
- **`MAX_MESSAGE_BYTES = 16 MiB`** on both server and client receive paths —
  the 4-byte length prefix previously allowed a peer to force up to a
  4 GiB allocation before any decryption happened.

Verified by: `TestConnectionRateLimiter` (4), `TestFrameBound` (2).

### 2.4 Secure bind defaults

The tool's own services now default to loopback; operators opt into wider
binds explicitly:

- `RATC2Server` (`rat_c2.py`) and `RATIntegration.start_server`
- `SecureC2Server` (`rat_c2_secure.py`) — also fixed a real bug where the
  constructor's `host` parameter was ignored and the socket always bound
  `'0.0.0.0'`
- `NativeC2Server` + the `c2` subcommand (`raphael_cli.py`)

Verified by: `TestSecureBindDefaults` (3).

### 2.5 Dependency pins

All three requirements files (`requirements.txt`, `configs/requirements.txt`,
`src/agent/requirements.txt`) and the `pyproject.toml` optional-dependency
groups now carry **validated lower bounds plus upper bounds at the next
major (next minor for 0.x)**. The suite runs green against the installed
versions inside those ranges. Loosening a cap is now a deliberate review
decision, not an accident of `pip install`.

### 2.6 Portability (author-machine paths removed)


- `src/orchestrator/config/paths.py` / `target.py` — were
  `sys.path.insert(0, "/home/yaser/raphael-2.0")` + `from config.* import *`,
  which raised `ModuleNotFoundError` on any other machine (and silently
  masked the fact that the package lives at the repo root as `configs`).
  Now derived from `__file__` and importing `configs.*`.
- 11 arena scripts (`d7`–`d16` runners/diagnostics) — same treatment for
  their `sys.path` bootstrap and their hardcoded result/manifest output
  paths (`arena/results/…`, `arena/d6c_results/…`, `arena/manifests/…`).
- `src/recon-pipeline/main.py` and `src/bridge/raphael_bridge.py` — derived
  their import root (`src/`) from `__file__` instead of
  `/home/yaser/raphael-2.0`, so both services import cleanly from any
  checkout.
- `src/raphael/techniques/ad1_xor_sweep.py` plus the four `d6*` validation
  runners, `scripts/phase0_audit.py`, `scripts/run_challenge000.py` and the
  two `test_d5*.py` preflight proofs — same treatment; the AD1 path is
  now `AD1_PATH`-overridable with a repo-relative default and the script
  exits 2 with an actionable message when the engagement image is absent.
- `.gitignore`: anchored the `arena/` exclusion to `/arena/`. The previous
  unanchored rule silently masked all 8,745 tracked files under
  `src/arena/`, so any new source file added there was never seen. The rule
  now ignores only the root output directory.
- `src/cloak_service/__init__.py`: added the package marker so setuptools
  (`find` with `include=["cloak_service*"]`) actually ships it — the
  recon agent already imported `cloak_service.cloakbrowser`, which worked
  from a source checkout as a namespace package but was dropped from a
  wheel.
- `configs/hrm_service.conf`: deleted — `orchestrator.hrm_service` does
  not exist in the tree and no code references it; it was a template only
  (blocker B8 closed).
- `configs/judge_report.json`: a historical machine-generated artifact
  retained as evidence. Its embedded `/home/yaser/…` evidence paths are
  frozen snapshots of where results lived when they were produced; nothing
  in the tool reads this file at runtime (it is regenerated by
  `scripts/JUDGE.py` into `scripts/judge_report.json`, which is gitignored).

The four root-level `cai_service` / `cloak_service` / `mcp_hub` /
`mhddos_service` symlinks listed as a remaining gap in earlier drafts were
already removed in commit `db82201c` ("Remove Docker dependency; wire
harness into orchestrator") — nothing to fix there.

Verified by: `TestPortability` (3) plus import smoke checks for every
service module whose bootstrap path was changed.

Additional landings in this reconciliation pass:
- `scripts/run_help.sh` / `scripts/test_command.sh` — author-root `cd` replaced with
  repo-relative + venv-python invocation.
- B8 closure: `configs/hrm_service.conf` deleted (module absent, no consumer).
- B7 closure: `.gitignore` strengthened so the residual planning artefacts
  (including `AUDIT_REPORT_2026-11-03.md` fallback snapshot) never publish.


### 2.7 Version single-sourcing

`raphael-ma` reported `0.3.0` while the package is `3.1.0`.
`src/raphael/multiagent/__init__.py` now prefers installed package metadata
(`importlib.metadata.version("raphael-black")`) with a source-checkout
fallback, and `TestVersionSingleSourcing` asserts agreement with
`pyproject.toml` so the skew cannot silently return.

### 2.8 Test-infrastructure root fixes

- Missing `Tuple` import (`src/harness/ai_exploit_generator.py`) and
  missing `Evidence` import (`src/orchestrator/brain/contradiction.py`)
  unblocked collection of 8 test modules (61 previously invisible tests).
- `tests/test_raphael_multiagent_chat.py` constructs its `CliRunner` with
  separated streams (`mix_stderr=False` on click < 8.2; click ≥ 8.2
  separates by default) so the `--json` contract — pure NDJSON on stdout,
  human diagnostics on stderr — is asserted for what it is, not for what
  a particular click version happens to mix together.

## 3. Verification summary

- `pytest -q` → **260 passed / 0 failed** (230 baseline restored at
  the root + 21 new hardening regressions + 7 debate improvement tests
  + 2 tests added in pass #2), ~150s. Bare `pytest` collects exactly
  `tests/` after fixing `testpaths` INI syntax.
- Live headless boot of all six TUI screens (F1/F3/F4/F5/F6/F12) — OK.
- CLI surface end-to-end: `init`, `--json chat` (pure NDJSON on stdout,
  banner on stderr), `brain log`, `tui` — OK.
- Legacy C2 live socket smoke: beacon → ack over AES-256-GCM, per-IP rate
  limit enforced, oversized frame dropped — OK.
- Credential-pattern scan over the full diff and new files — clean.

## 4. Recommended follow-ups (not blocking)

1. ~~Remove or gitignore the four dangling root service symlinks~~ — already
   removed in commit `db82201c` ("Remove Docker dependency; wire harness
   into orchestrator"); four dangling root symlinks no longer exist. Closed.
2. Migrate any remaining `rat_c2` consumers to `rat_c2_secure`
   (mTLS + challenge-response) and deprecate the legacy surface.
3. Add a CI job that installs from the pinned ranges from scratch and runs
   the suite, so cap loosening is always a reviewed change.
4. Introduce a lockfile (`pip-compile` / `uv lock`) for reproducible
   deployment environments.
