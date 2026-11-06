"""Verify all v3.1 + RAT imports work correctly."""
from harness import (
    # Core
    BlackHatHarness,
    BlackHatConfig,
    UnifiedBroker,
    AuditSink,
    EmergencyKillSwitch,
    # Stealth
    KernelRootkit,
    UEFIRootkit,
    DomainFrontingC2,
    CrossPlatformImplant,
    # C2 (including RAT)
    RATC2Server,
    Implant,
    ImplantStatus,
    # Exploitation (including RAT)
    RATIntegration,
    RATOperationResult,
    RATCampaignResult,
    create_rat_integration,
    ApacheTraversalExploit,
    VsftpdBackdoorExploit,
    EternalBlueExploit,
    BlueKeepExploit,
    MySQLAuthBypassExploit,
    get_exploit_module,
    list_available_modules,
)
print("All v3.1 + RAT imports successful")

# Verify exploit modules can be instantiated
module = get_exploit_module("CVE-2021-41773")
assert module is not None
assert module.name == "Apache Traversal RCE"
print(f"Exploit module loaded: {module.name} ({module.cve_id})")

modules = list_available_modules()
assert len(modules) == 5
print(f"Available exploit modules: {len(modules)}")
for m in modules:
    print(f"  - {m['cve_id']}: {m['name']} ({m['service']}:{m['port']})")

print("\n=== All imports verified ===")
