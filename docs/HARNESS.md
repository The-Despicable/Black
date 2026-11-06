# Native Harness

The.Parcelable `src/harness` package provides a guarded, audit-first wrapper for future controlled workflows.

Core pieces:
- `models.py`: Action requests, target scope, authorization decisions.
- `authorization.py`: Dual-gate scope + action approval.
- `process_manager.py`: Native tool diagnostics.
- `research.py`: Source URLs and paper bundle normalization.
- `harness.py`: Async lifecycle, audit trail, guarded submission.
- `cli.py`: `doctor` and `run` commands.

The harness intentionally disables operational scanning or exploitation until scope-aware execution modules are explicitly added.