# ADR 0004 — Audit Trail Unification: Single Cryptographic Audit Sink

## Status
Accepted

## Context
Audit #3 and #5 found that the guarded harness has an audit trail (`AuditTrail` in `harness/harness.py`) but the Black Hat engine does not. Operational activity in BH is not centrally accountable.

## Decision
Create a unified `AuditSink` that:
- Writes to `logs/harness_audit.jsonl` in JSONL format
- Uses cryptographic chaining (each entry's hash includes previous entry's hash)
- Is tamper-evident: any modification breaks the chain
- Is consumed by both guarded harness (`RaphaelHarness`) and BH engine (`BlackHatHarness`)

## Rationale
- Single source of truth for all authorization and execution decisions
- Tamper-evident chain prevents undetectable log modification
- Async-safe for concurrent operation logging

## Consequences
- All BH operations generate audit entries
- `verify_chain()` method validates integrity
- Log rotation must preserve chain integrity

## Related
- src/harness/governance/audit_sink.py
- Audit #3: Critical untested paths — anti-forensic evasion validation
- Audit #5: Audit trail completeness — BH core weak
