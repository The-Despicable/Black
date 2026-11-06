"""
harness.governance.audit_sink — Audit sink for governance subsystem.

Re-exports AuditSink from black_hat_core for backward compatibility.
"""

from harness.black_hat_core import AuditSink

__all__ = ["AuditSink"]
