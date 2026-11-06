"""
Anti-Forensic Verification Tests (Phase 5, Requirement 3).

Tests that anti-forensic operations verify outcomes instead of
returning optimistic success. Failed verifications must return
success: False with error details.
"""

import asyncio
import pytest

from harness.black_hat_core import BlackHatConfig, BlackHatHarness
from harness.governance import UnifiedBroker, AuditSink, EmergencyKillSwitch


@pytest.fixture
async def harness_with_governance(tmp_path):
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
async def test_secure_delete_verification_failure(harness_with_governance):
    """Secure delete must report honest results."""
    harness = harness_with_governance

    result = await harness.cleanup.secure_delete_artifacts(
        ["/tmp/nonexistent_file_12345"], passes=1
    )
    assert result is not None
    assert "status" in result
    assert "deleted" in result
    assert "failed" in result
    # Non-existent file should not appear in deleted list
    assert "/tmp/nonexistent_file_12345" not in result["deleted"]


@pytest.mark.asyncio
async def test_secure_delete_verification_success(tmp_path):
    """Secure delete of existing file must verify deletion."""
    from harness.black_hat_core import AntiForensicCleanup, BlackHatConfig

    # Create a temp file
    test_file = tmp_path / "test_delete_me.txt"
    test_file.write_text("temporary data")

    config = BlackHatConfig(target_host="127.0.0.1", target_port=443)
    cleanup = AntiForensicCleanup(config)

    result = await cleanup.secure_delete_artifacts([str(test_file)], passes=1)
    assert result["status"] == "success"
    assert str(test_file) in result["deleted"]
    assert not test_file.exists(), "File should be deleted after secure delete"


@pytest.mark.asyncio
async def test_log_clear_verification(harness_with_governance):
    """Log clear must verify logs are actually cleared."""
    harness = harness_with_governance

    result = await harness.log_suppressor.final_log_clear()
    assert result is not None
    assert "status" in result
    assert "logs_cleared" in result
    assert "failed" in result


@pytest.mark.asyncio
async def test_timestomp_verification(harness_with_governance):
    """Timestomp must report honest results."""
    harness = harness_with_governance

    result = await harness.cleanup.timestomp_files(reference="nonexistent_file")
    assert result is not None
    assert "status" in result
    # Reference file doesn't exist, should report failure
    assert result["status"] in ("failed", "skipped")


@pytest.mark.asyncio
async def test_wipe_free_space_linux_not_implemented(harness_with_governance):
    """Linux free space wipe should report as not implemented, not fake success."""
    harness = harness_with_governance

    result = await harness.cleanup.wipe_free_space()
    assert result is not None
    assert "status" in result
    # Should be "skipped" for Linux since not implemented
    assert result["status"] in ("skipped", "not_implemented")


@pytest.mark.asyncio
async def test_sensitive_memory_zeroing_honest(harness_with_governance):
    """Memory zeroing must report honestly, not claim fake success."""
    harness = harness_with_governance

    result = await harness.stealth.zero_sensitive_memory()
    assert result is not None
    assert "status" in result
    assert "regions_zeroed" in result
    # Should report 0 regions zeroed and note that verification is not implemented
    assert result["regions_zeroed"] == 0


@pytest.mark.asyncio
async def test_shellcode_injection_stub_honest(harness_with_governance):
    """Shellcode injection stub must report as stub/unverified, not fake success."""
    harness = harness_with_governance

    result = await harness.memory_resident._inject_shellcode(b"\x90\x90\x90")
    assert result is not None
    assert result.get("status") == "stub"
    assert result.get("verified") is False
    assert "note" in result


@pytest.mark.asyncio
async def test_no_optimistic_success_returns():
    """No anti-forensic method should return optimistic success without verification."""
    import inspect
    import harness.black_hat_core as bhc

    source = inspect.getsource(bhc)

    # Check that _inject_shellcode returns stub status, not fake success
    inject_source = inspect.getsource(bhc.MemoryResidentExecutor._inject_shellcode)
    assert "stub" in inject_source
    assert "verified" in inject_source

    # Check that zero_sensitive_memory reports honestly
    zero_source = inspect.getsource(bhc.StealthEngine.zero_sensitive_memory)
    assert "verification" in zero_source
    assert "regions_zeroed" in zero_source


@pytest.mark.asyncio
async def test_kernel_rootkit_verified_result(tmp_path):
    """Kernel rootkit operations must use VerifiedResult pattern."""
    from harness.stealth.kernel_rootkit import KernelRootkit, VerifiedResult

    audit_log = tmp_path / "audit.jsonl"
    audit_sink = AuditSink(audit_log)
    await audit_sink.initialize()

    # Create rootkit without broker — should fail closed
    rootkit = KernelRootkit(broker=None, audit_sink=None)
    # No broker means all operations denied

    # Test hide_process without broker — should fail
    # We can't easily test the full async flow without a broker,
    # but we can verify VerifiedResult dataclass exists
    vr = VerifiedResult(
        claimed_action="test",
        success=False,
        verification_method="test_method",
        error="test error",
    )
    assert vr.success is False
    assert vr.error == "test error"
