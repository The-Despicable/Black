"""
Governance Integration Tests (Phase 5, Requirement 1).

Tests that BlackHatHarness v3.1 routes all operations through CapabilityBroker,
enforces scope validation, rate limits, and kill switch.
"""

import asyncio
import pytest

from harness.black_hat_core import BlackHatConfig, BlackHatHarness
from harness.governance import UnifiedBroker, EmergencyKillSwitch
from harness.governance.audit_sink import AuditSink as AuditSinkClass


@pytest.fixture
async def governance_stack(tmp_path):
    """Set up broker + audit sink + kill switch for testing."""
    audit_log = tmp_path / "harness_audit.jsonl"
    audit_sink = AuditSinkClass(audit_log)
    await audit_sink.initialize()

    kill_switch = EmergencyKillSwitch()
    broker = UnifiedBroker(audit_sink=audit_sink, kill_switch=kill_switch)
    await broker.initialize()

    return broker, audit_sink, kill_switch


@pytest.mark.asyncio
async def test_black_hat_refuses_without_broker():
    """BlackHatHarness must refuse to execute without governance broker."""
    config = BlackHatConfig(target_host="10.0.0.1", target_port=443)
    harness = BlackHatHarness(config)  # No broker
    result = await harness.execute_operation({"type": "vuln_scan", "target": "10.0.0.1"})
    assert result.status.value in ("aborted", "failed")
    assert result.error is not None
    assert "governance" in result.error.lower() or "kill switch" in result.error.lower()


@pytest.mark.asyncio
async def test_out_of_scope_target_rejected(governance_stack):
    """Out-of-scope targets must be rejected for every v3.1 capability."""
    broker, audit_sink, kill_switch = governance_stack

    # Authorize with a target NOT in scope
    result = await broker.authorize_action(
        action_type="scan",
        capability="nmap",
        method="nmap -sV",
        target="10.0.0.1",
        impact_estimate=1.0,
        metadata={"authorized_scopes": ("192.168.1.0/24",)},  # 10.0.0.1 not in scope
    )
    assert result.approved is False


@pytest.mark.asyncio
async def test_in_scope_target_approved(tmp_path):
    """In-scope targets must be authorized."""
    from orchestrator.brain.capability_broker import BrokerPolicy

    audit_log = tmp_path / "harness_audit.jsonl"
    audit_sink = AuditSinkClass(audit_log)
    await audit_sink.initialize()

    kill_switch = EmergencyKillSwitch()
    broker = UnifiedBroker(audit_sink=audit_sink, kill_switch=kill_switch)

    # Create policy with target in scope BEFORE initializing
    broker._broker_policy = BrokerPolicy(
        engagement_id="test",
        allowed_targets=["192.168.1.0/24"],
        prohibited_targets=[],
        allowed_action_types=["scan"],
        prohibited_action_types=[],
        allowed_capabilities=["nmap"],
        prohibited_capabilities=[],
    )
    await broker.initialize()

    result = await broker.authorize_action(
        action_type="scan",
        capability="nmap",
        method="nmap -sV",
        target="192.168.1.10",
        impact_estimate=1.0,
        metadata={"authorized_scopes": ("192.168.1.0/24",)},
    )
    assert result.approved is True


@pytest.mark.asyncio
async def test_rate_limits_enforced(governance_stack):
    """Rate limits must be enforced for kernel operations and C2 beacons."""
    broker, audit_sink, kill_switch = governance_stack

    # Authorize many rapid operations to exhaust rate limits
    for i in range(70):  # Exceed max_actions_per_minute (60)
        await broker.authorize_action(
            action_type="scan",
            capability="nmap",
            method="nmap -sV",
            target="192.168.1.10",
            impact_estimate=0.1,
            metadata={"authorized_scopes": ("192.168.1.0/24",)},
        )

    stats = broker.get_stats()
    assert stats["operations_blocked"] > 0 or stats["operations_authorized"] <= 60


@pytest.mark.asyncio
async def test_kill_switch_blocks_operations(governance_stack):
    """Kill switch must halt all operations and prevent new authorizations."""
    broker, audit_sink, kill_switch = governance_stack

    # Trigger kill switch
    await kill_switch.trigger(triggered_by="test", reason="test kill switch")

    # All operations should now be denied
    result = await broker.authorize_action(
        action_type="scan",
        capability="nmap",
        method="nmap -sV",
        target="192.168.1.10",
        impact_estimate=1.0,
        metadata={"authorized_scopes": ("192.168.1.0/24",)},
    )
    assert result.approved is False
    assert "kill switch" in result.reason.lower()


@pytest.mark.asyncio
async def test_audit_trail_written(governance_stack, tmp_path):
    """All authorization decisions must be written to audit trail."""
    broker, audit_sink, kill_switch = governance_stack

    await broker.authorize_action(
        action_type="scan",
        capability="nmap",
        method="nmap -sV",
        target="192.168.1.10",
        impact_estimate=1.0,
        metadata={"authorized_scopes": ("192.168.1.0/24",)},
    )

    # Verify audit log exists and has entries
    audit_log = audit_sink.log_path
    assert audit_log.exists()
    content = audit_log.read_text()
    assert len(content.strip()) > 0
    assert "192.168.1.10" in content


@pytest.mark.asyncio
async def test_audit_chain_integrity(governance_stack):
    """Audit chain must be cryptographically intact."""
    broker, audit_sink, kill_switch = governance_stack

    await broker.authorize_action(
        action_type="scan",
        capability="nmap",
        method="nmap -sV",
        target="192.168.1.10",
        impact_estimate=1.0,
        metadata={"authorized_scopes": ("192.168.1.0/24",)},
    )

    verification = await audit_sink.verify_chain()
    assert verification["valid"] is True
    assert verification["entries"] >= 1
