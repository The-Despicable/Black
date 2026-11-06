# Safety & Authorization — Raphael Black Hat Harness v3.1

## Authorization Requirement

**ALL capabilities in the Raphael Black Hat Harness require explicit authorization.** No operation may execute without passing through the `UnifiedBroker` → `CapabilityBroker` governance layer.

## Governance Controls

### Dual-Gate Authorization

Every action must pass two gates:

1. **Connection Gate**: Target must be in authorized scope; not in prohibited targets.
2. **Action Gate**: Action type and capability must be explicitly allowed; rate limits and impact budget must not be exceeded.

### Fail-Closed

If the governance broker is unavailable, all operations are denied. There is no bypass.

### Kill Switch

The `EmergencyKillSwitch` can halt all operations instantly:
- Cancels all active async operations
- Disables new operation authorization
- Triggers emergency cleanup in all subsystems
- Puts all C2 channels in dark mode

Accessible via CLI: `raphael kill-switch`

## Lab-Only Configuration

For isolated lab testing:

```yaml
authorization:
  engagement_id: "lab-test-001"
  allowed_scopes:
    - "10.0.0.0/8"   # Lab network only
  prohibited_targets: []
  allowed_action_types: ["scan", "exploit"]
  allowed_capabilities: ["nmap", "php2shell"]
  rate_limits:
    max_actions_per_minute: 10
    max_concurrent: 2
  impact_budget:
    max_impact_per_action: 3.0
    max_cumulative_impact: 10.0

capabilities:
  kernel_rootkit: false
  uefi_persistence: false
  ai_evasion: false
  zero_day_framework: false

stealth:
  anti_forensics: false
  memory_resident: false
```

## Authorized Engagement Configuration

For authorized red team operations:

```yaml
authorization:
  engagement_id: "rt-2024-001"
  allowed_scopes:
    - "client.corp.local"
    - "10.10.0.0/16"
  prohibited_targets:
    - "10.10.99.0/24"  # Production database - off limits
  allowed_action_types: ["recon", "scan", "exploit", "persistence"]
  rate_limits:
    max_actions_per_minute: 30
    max_concurrent: 5
  impact_budget:
    max_impact_per_action: 5.0
    max_cumulative_impact: 50.0
    high_impact_requires_approval: true

capabilities:
  kernel_rootkit: true
  domain_fronting_c2: true
  cross_platform_implant: true

audit:
  log_path: "logs/harness_audit.jsonl"
  cryptographic_chaining: true
```

## Prohibited Uses

- Operations against targets not in authorized scope
- Operations without explicit engagement authorization
- Anti-forensic operations without outcome verification
- Bypassing the governance layer
- Disabling the kill switch during active operations

## Audit Trail

All operations are logged to `logs/harness_audit.jsonl` with cryptographic chaining. Run `python -m configs.config_validator --config configs/raphael.yaml` to validate configuration integrity.
