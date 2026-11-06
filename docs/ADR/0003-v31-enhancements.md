# ADR 0003 — v3.1 Enhancements: Kernel Rootkit, UEFI Persistence, AI Evasion, Distributed C2

## Status
Accepted

## Context
The v3.1 code adds maximum power capabilities: kernel-level rootkit, UEFI/BIOS persistence, SPI flash access, AI-driven adaptive evasion, distributed C2 (domain fronting, dead drop, P2P), zero-day exploitation framework, and cross-platform implant. These must be integrated while maintaining governance.

## Decision
Integrate all v3.1 capabilities as governance-aware modules under `src/harness/`:
- `src/harness/stealth/` — KernelRootkit, UEFIRootkit, SPIFlashAccess, AdaptiveEvasionEngine, BehavioralMimicry
- `src/harness/c2/` — DomainFrontingC2, DeadDropResolverC2, P2PC2Network
- `src/harness/exploitation/` — FuzzingEngine, ExploitGenerator
- `src/harness/implant/` — CrossPlatformImplant

Each component accepts optional `broker` and `audit_sink` parameters and must authorize before execution.

## Rationale
- Provides maximum offensive capability while maintaining accountability
- All operations audited and authorized
- Fail-closed: without governance, capabilities cannot execute

## Consequences
- Significant increase in offensive power — must be used only with proper authorization
- Kernel and UEFI operations require root/admin and may not work in all environments
- Anti-forensic operations include outcome verification (no optimistic success)

## Related
- src/harness/stealth/kernel_rootkit.py
- src/harness/stealth/hardware_persistence.py
- src/harness/stealth/adaptive_evasion.py
- src/harness/c2/distributed_c2.py
- src/harness/exploitation/zero_day_framework.py
- src/harness/implant/cross_platform_implant.py
