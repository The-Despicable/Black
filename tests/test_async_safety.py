"""
Async Safety Tests (Phase 5, Requirement 2).

Tests that BH executors work inside a running event loop,
no `run_until_complete` anti-patterns, and concurrent operations are safe.
"""

import asyncio
import pytest

from harness.black_hat_core import BlackHatConfig, BlackHatHarness
from harness.governance import UnifiedBroker, AuditSink, EmergencyKillSwitch


@pytest.fixture
async def harness_with_governance(tmp_path):
    """Create a BlackHatHarness with governance for testing."""
    audit_log = tmp_path / "harness_audit.jsonl"
    audit_sink = AuditSink(audit_log)
    await audit_sink.initialize()

    kill_switch = EmergencyKillSwitch()
    broker = UnifiedBroker(audit_sink=audit_sink, kill_switch=kill_switch)
    await broker.initialize()

    config = BlackHatConfig(target_host="192.168.1.10", target_port=443)
    harness = BlackHatHarness(
        config, broker=broker, audit_sink=audit_sink, kill_switch=kill_switch
    )
    return harness


@pytest.mark.asyncio
async def test_bh_executor_in_running_event_loop(harness_with_governance):
    """BH executors must work when called from within a running event loop."""
    harness = harness_with_governance

    # This test runs inside an event loop (pytest-asyncio)
    # The harness's execute_operation uses await throughout — no run_until_complete
    result = await harness.execute_operation(
        {"type": "vuln_scan", "target": "192.168.1.10", "ports": "80,443"}
    )
    # Should not raise RuntimeError: This event loop is already running
    assert result is not None
    assert result.status is not None


@pytest.mark.asyncio
async def test_no_run_until_complete_anti_pattern():
    """Verify no BH executor uses asyncio.get_event_loop().run_until_complete()."""
    import inspect
    import harness.black_hat_core as bhc

    # Check black_hat_core source for run_until_complete
    source = inspect.getsource(bhc)
    assert "run_until_complete" not in source, "run_until_complete found in black_hat_core"

    # Check that all methods are async-native
    assert asyncio.iscoroutinefunction(BlackHatHarness.execute_operation)


@pytest.mark.asyncio
async def test_concurrent_operations_safe(harness_with_governance):
    """Concurrent BH operations must be handled with proper locking."""
    harness = harness_with_governance

    # Launch multiple operations concurrently
    tasks = []
    for i in range(5):
        task = harness.execute_operation(
            {"type": "vuln_scan", "target": f"192.168.1.{10 + i}", "ports": "80"}
        )
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # No exceptions should occur
    for r in results:
        assert not isinstance(r, Exception), f"Concurrent operation raised: {r}"
        assert r is not None


@pytest.mark.asyncio
async def test_async_bridge_no_event_loop_conflict(harness_with_governance):
    """Async executor bridge must not conflict with running event loops."""
    harness = harness_with_governance

    # Call execute_operation multiple times in sequence within same loop
    for i in range(3):
        result = await harness.execute_operation(
            {"type": "vuln_scan", "target": f"10.0.0.{i}", "ports": "22"}
        )
        assert result.status is not None


@pytest.mark.asyncio
async def test_stealth_engine_async_methods(harness_with_governance):
    """Stealth engine methods must be async-native."""
    harness = harness_with_governance

    # Test async stealth methods
    etw_result = await harness.stealth.patch_etw()
    assert etw_result is not None
    assert "status" in etw_result

    amsi_result = await harness.stealth.patch_amsi()
    assert amsi_result is not None
    assert "status" in amsi_result

    zero_result = await harness.stealth.zero_sensitive_memory()
    assert zero_result is not None
    assert "status" in zero_result


@pytest.mark.asyncio
async def test_memory_resident_async_methods(harness_with_governance):
    """Memory resident executor methods must be async-native."""
    harness = harness_with_governance

    prepare_result = await harness.memory_resident.prepare()
    assert prepare_result is not None
    assert "status" in prepare_result

    inject_result = await harness.memory_resident._inject_shellcode(b"\x90\x90")
    assert inject_result is not None
    assert "status" in inject_result
    # Should report as stub (honest), not fake success
    assert inject_result.get("verified") is False or inject_result.get("status") == "stub"


@pytest.mark.asyncio
async def test_log_suppressor_verification(harness_with_governance):
    """Log suppression must verify outcomes, not return optimistic success."""
    harness = harness_with_governance

    result = await harness.log_suppressor.final_log_clear()
    assert result is not None
    assert "status" in result
    # Status should be "success" or "partial" — not blindly claiming success
    assert result["status"] in ("success", "partial", "skipped")


@pytest.mark.asyncio
async def test_anti_forensic_cleanup_verification(harness_with_governance):
    """Anti-forensic cleanup must verify outcomes."""
    harness = harness_with_governance

    result = await harness.cleanup.secure_delete_artifacts(["/tmp/nonexistent_test_file"], passes=1)
    assert result is not None
    assert "status" in result
    assert "deleted" in result
    assert "failed" in result
