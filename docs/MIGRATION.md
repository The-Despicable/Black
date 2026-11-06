# Migration Guide: v2 Cognitive Platform → v3.1 Black Hat Harness

## Overview

This guide maps v2 cognitive platform components to their v3.1 Black Hat Harness equivalents and documents breaking changes.

## Component Mapping

| v2 Component | v3.1 Equivalent | Status |
|-------------|-----------------|--------|
| `src/orchestrator/brain/` | `src/harness/governance/unified_broker.py` | Migrated |
| `src/orchestrator/capability_broker.py` | `src/harness/governance/unified_broker.py` | Unified |
| `src/harness/black_hat_core.py` | `src/harness/black_hat_core.py` (v3.1 with governance) | Enhanced |
| `src/harness/black_hat_cli.py` | `src/harness/black_hat_cli.py` (v3.1 with governance) | Enhanced |
| `src/harness/stealth/kernel_rootkit.py` | NEW | v3.1 |
| `src/harness/stealth/hardware_persistence.py` | NEW | v3.1 |
| `src/harness/stealth/adaptive_evasion.py` | NEW | v3.1 |
| `src/harness/c2/distributed_c2.py` | NEW | v3.1 |
| `src/harness/exploitation/zero_day_framework.py` | NEW | v3.1 |
| `src/harness/implant/cross_platform_implant.py` | NEW | v3.1 |

## Breaking Changes

1. **BlackHatHarness now requires governance**: `BlackHatHarness(config)` without a broker will abort all operations. Use `UnifiedBroker` to create governance-enabled instances.

2. **No more `run_until_complete`**: All BH executors are async-native. Replace `asyncio.get_event_loop().run_until_complete()` with `await`.

3. **Package scope narrowed**: `pyproject.toml` only includes `harness*` and `cloak_service*`. Legacy `orchestrator`, `raphael`, `agent` modules require `PYTHONPATH=src`.

4. **Optimistic anti-forensic returns removed**: All anti-forensic operations verify outcomes and report honestly.

## Migration Example

### Before (v2):
```python
config = BlackHatConfig(target_host="10.0.0.1")
harness = BlackHatHarness(config)
result = await harness.execute_operation({"type": "vuln_scan"})
```

### After (v3.1):
```python
from harness.governance import UnifiedBroker, AuditSink, EmergencyKillSwitch

audit_sink = AuditSink(Path("logs/harness_audit.jsonl"))
await audit_sink.initialize()
kill_switch = EmergencyKillSwitch()
broker = UnifiedBroker(audit_sink=audit_sink, kill_switch=kill_switch)
await broker.initialize()

config = BlackHatConfig(target_host="10.0.0.1")
harness = BlackHatHarness(config, broker=broker, audit_sink=audit_sink, kill_switch=kill_switch)
result = await harness.execute_operation({"type": "vuln_scan"})
```

## Docker Removal

All Docker Compose files have been moved to `legacy/deployment/`. The project is now native-only. Use `pip install -e .` for installation.
