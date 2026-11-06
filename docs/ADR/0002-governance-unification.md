# ADR 0002 — Governance Unification: BH Engine Routes Through CapabilityBroker

## Status
Accepted

## Context
Audit #1, #5, and #7 identified that `BlackHatHarness` and `black_hat_cli.py` bypass the governance layer entirely — they do not use `CapabilityBroker`, `HarnessConfig`, or the audit trail. This is the primary security gap in the repository.

## Decision
All Black Hat Harness v3.1 operations MUST route through a `UnifiedBroker` that wraps the orchestrator `CapabilityBroker`. Every operation (scan, exploit, persistence, C2, anti-forensic, kernel rootkit, UEFI modification) must:
1. Generate an `ActionRequest`
2. Pass through `CapabilityBroker.authorize_action()` with dual-gate authorization
3. Generate a structured audit receipt in the unified `AuditSink`
4. Respect the `EmergencyKillSwitch`

## Rationale
- Fail-closed: if governance is unavailable, ALL operations are denied
- Single audit trail for guarded harness, BH engine, and cognitive orchestrator
- Centralized kill switch for emergency response
- Scope validation prevents out-of-bounds operations

## Consequences
- `BlackHatHarness.__init__()` now accepts optional `broker`, `audit_sink`, `kill_switch` parameters
- `black_hat_cli.py` initializes governance before executing operations
- All async `run_until_complete` anti-patterns replaced with proper `await`
- Optimistic anti-forensic success returns replaced with outcome verification

## Related
- Audit #1: Section 5.1 (Guarded harness bypass)
- Audit #5: Section 5.1 (Operational engine bypasses governance)
- src/harness/governance/: UnifiedBroker, AuditSink, KillSwitch
