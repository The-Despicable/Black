"""
harness.governance — Governance subsystem for BlackHatHarness v3.1.

Re-exports the core governance components from black_hat_core:
  - UnifiedBroker    (authorization gateway with fail-closed semantics)
  - AuditSink         (cryptographic audit trail logging)
  - EmergencyKillSwitch (dead man's switch + emergency stop)

Tests import from harness.governance; this module maintains backward compatibility
by re-exporting the classes from harness.black_hat_core.
"""

from harness.black_hat_core import (
    UnifiedBroker,
    AuditSink,
    EmergencyKillSwitch,
)

__all__ = [
    "UnifiedBroker",
    "AuditSink",
    "EmergencyKillSwitch",
]
