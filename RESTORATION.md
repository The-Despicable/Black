# Raphael_Black — Full Restoration Guide

## Repository Information
- **Repository**: git@github.com:The-Despicable/Black.git
- **Package**: `raphael-black` (v3.1.0)
- **Branch**: `main`
- **SSH Key Fingerprint**: `SHA256:IAG15POUhvEjvHl+jjEhscCQVduHNP3lgugKl46viIg`

---

## Quick Start

```bash
# 1. Clone the repository
git clone git@github.com:The-Despicable/Black.git Raphael_Black
cd Raphael_Black

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install package (editable mode)
pip install -e .

# 4. Install system dependencies (Linux)
sudo apt-get update && sudo apt-get install -y \
    nmap sqlmap hydra tor \
    coreutils wipe bleachbit iodine obfs4proxy steghide \
    chkrootkit rkhunter lynis auditd unhide tcplay \
    golang-go

# 5. Install Go-based tools
go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
go install github.com/jpillora/chisel@latest

# 6. Install CloakBrowser (for research)
python3 -m cloakbrowser install
python3 -m playwright install chromium

# 7. Verify installation
raphael --help
```

---

## Project Structure

```
Raphael_Black/
├── src/
│   ├── harness/                    # Black Hat Harness v3.1
│   │   ├── __init__.py             # Exports all modules
│   │   ├── black_hat_core.py       # Core orchestrator
│   │   ├── ltad_engine.py          # Live Target Adaptive Exploitation
│   │   ├── php2shell.py            # Polymorphic PHP webshells (14 variants)
│   │   ├── ai_exploit_generator.py # AI-driven exploit generation (GA)
│   │   ├── rat_c2.py               # RAT C2 with Fernet encryption
│   │   ├── exploits.py             # CVE modules (5 CVEs)
│   │   ├── black_hat_cli.py        # Unified CLI (10 commands)
│   │   ├── governance/             # Audit sink, kill switch
│   │   ├── stealth/                # Kernel rootkit, UEFI rootkit
│   │   ├── weaponized_agent.py     # Cross-platform agent
│   │   ├── research.py             # Research module
│   │   ├── c2.py                   # Domain fronting C2
│   │   ├── harness.py              # Main harness class
│   │   ├── implant.py              # Implant management
│   │   └── models.py               # Data models
│   │
│   ├── cloak_service/              # CloakBrowser service
│   │   ├── Dockerfile
│   │   ├── cloakbrowser.py         # Stealth browser (Playwright)
│   │   ├── main.py                 # FastAPI on port 3401
│   │   └── requirements.txt
│   │
│   ├── raphael/multiagent/         # Multi-agent system
│   │   ├── brain/                  # Brain modules
│   │   ├── orchestrators/          # Orchestration
│   │   ├── llm/                    # LLM integration
│   │   ├── tui/                    # Terminal UI
│   │   └── cli.py                  # raphael-ma command
│   │
│   ├── orchestrator/               # Cognitive orchestrator
│   │   ├── agents/                 # Exploit, Recon, Scan agents
│   │   ├── brain/                  # World model, planner, broker
│   │   ├── capabilities/           # Shell capabilities
│   │   ├── chains/                 # Tool registry
│   │   ├── postex/                 # Post-exploitation
│   │   └── agents/                 # Agent implementations
│   │
│   ├── agent/                      # Implant agent
│   │   ├── modules/                # Stealth, credtheft, exfil, etc.
│   │   ├── agent.py                # Main agent
│   │   ├── crypto.py               # AESGCM + Ed25519
│   │   └── audit.py                # Audit logging
│   │
│   ├── c2-server/                  # Sliver/PupyC2 integration
│   ├── recon-pipeline/             # Automated recon
│   ├── phishing/                   # Gophish integration
│   └── kali-tools/                 # Kali tool wrappers
│
├── configs/                        # Configuration files
│   ├── raphael.yaml
│   ├── harness.yaml
│   └── config_validator.py
│
├── docs/                           # Documentation
│   ├── ARCHITECTURE.md
│   ├── HARNESS.md
│   ├── SAFETY.md
│   ├── API.md
│   └── ADR/                        # Architecture Decision Records
│
├── tests/                          # Test suite
│   ├── test_anti_forensic_verification.py
│   ├── test_harness_smoke.py
│   ├── test_v31_integration.py
│   └── test_raphael_multiagent_*.py
│
├── pyproject.toml                  # Package config (raphael-black)
├── install.sh                      # Native installer
├── requirements.txt
├── README.md
├── RESTORATION.md                  # This file
└── verify_imports.py               # Import verification
```

---

## CLI Commands

```bash
# Full black hat operation
raphael exploit --target 192.168.1.100 --port 443 --stealth maximum

# Broad vulnerability scan
raphael scan --target 10.0.0.0/24 --ports 1-1000

# Live target adaptive exploitation
raphael exploit-live --host 192.168.1.100 --port 80

# PHP2Shell webshell implantation
raphael php2shell --target-url http://target/upload.php --lfi-param page

# Research via CloakBrowser
raphael research --query "CVE-2024-XXXX" --sources scihub,exploitdb

# AI-driven exploit generation
raphael ai-generate --target 192.168.1.100 --vuln-type sqli --cycles 15

# RAT C2 server
raphael rat-server --port 443 --key <base64-fernet-key>

# CVE exploit modules
raphael exploit-module CVE-2021-41773 example.com --check-only

# List all exploits
raphael list-exploits

# Generate Fernet key
raphael generate-key
```

---

## Harness Modules

### 1. BlackHatHarness (`black_hat_core.py`)
Main orchestrator with:
- `StealthEngine` — ETW/AMSI patching, memory zeroing, timing jitter
- `MemoryResidentExecutor` — Donut/PEzor fileless execution
- `LogSuppressor` — Invoke-Phant0m, auditpol, log clearing
- `NetworkCloak` — JA3 spoofing, domain fronting, exfiltration
- `DatabaseExploiter` — MySQL/PostgreSQL/MSSQL protocols
- `AntiForensicCleanup` — Secure delete, timestomp, free space wipe
- `UnifiedBroker` — Dual-gate authorization
- `EmergencyKillSwitch` — Dead man's switch

### 2. LTAE Engine (`ltad_engine.py`)
Live Target Adaptive Exploitation:
- Real-time target state machine (7 states)
- Behavioral baselining & deception scoring
- WAF/IPS detection with fingerprinting
- Adaptive evasion with polymorphic payloads
- 4 probe types: SQLi, XSS, CMD injection, Path traversal
- Up to 3 evasion rounds per probe

### 3. PHP2Shell (`php2shell.py`)
14 polymorphic webshell variants:
- Basic, Obfuscated, Encoded, Chunked
- Variable Rename, Dead Code, String Split
- Eval Chain, Assert-based, Create Function
- Reflection, Anonymous Class, Generator, Fiber
- Filter chain exploitation for LFI/RFI
- Persistence via auto_prepend_file, .user.ini, htaccess

### 4. AI Exploit Generator (`ai_exploit_generator.py`)
Genetic algorithm evolution:
- Population size: 10, Cycles: 15
- Mutation rate: 0.3, Selection pressure: 0.7
- LLM integration (Ollama: codellama:13b-code)
- Fitness evaluation: static + dynamic + LLM
- Crossover + mutation operators

### 5. RAT C2 (`rat_c2.py`)
- Fernet encryption (AES-128-CBC + HMAC)
- Length-prefixed messaging protocol
- Server: Thread-per-session, daemon threads
- Client: Auto-reconnect with 30s backoff
- Commands: shell, upload, download, screenshot, keylog, persistence, migrate, uninstall
- Campaign management with multi-target support

### 6. CVE Exploit Modules (`exploits.py`)
| CVE | Service | Port | Description |
|-----|---------|------|-------------|
| CVE-2021-41773 | HTTP | 80 | Apache path traversal → RCE |
| CVE-2011-2523 | FTP | 21 | vsftpd 2.3.4 backdoor |
| CVE-2017-0144 | SMB | 445 | EternalBlue RCE |
| CVE-2019-0708 | RDP | 3389 | BlueKeep RCE |
| CVE-2012-2122 | MySQL | 3306 | Auth bypass (memcmp) |

---

## Orchestrator Integration

### ExploitAgent (`orchestrator/agents/exploit.py`)
- 20 tools registered (4 from harness)
- 52 technique mappings (16 harness techniques)
- 3-phase exploitation: Profile → Stack Exploit → Chain Synthesis → LLM Fallback

### Brain Modules (`orchestrator/brain/`)
- `world.py` — World model with 20+ entity types
- `action.py` — Planner with utility/cost/risk scoring
- `capability_broker.py` — Dual-gate authorization
- `waf_detector.py` — 7 WAF signatures
- `rate_limiter.py` — Per-target + global, 5-15s jitter
- `scope_parser.py` — HackerOne scope parsing

### ToolRegistry (`orchestrator/chains/tool_registry.py`)
- 10 tools total (4 harness tools)
- Harness tools: php2shell, ltad_exploit, memory_resident, php_filter_chain

### Agent Implant (`src/agent/`)
- `stealth.py` — AMSI/ETW bypass, syscall resolution, sleep masking
- `inject.py` — Process injection via indirect syscalls
- `credtheft.py` — Chrome, LSASS, SAM, SSH, K8s, cloud creds
- `exfil.py` — DNS, HTTPS, ICMP, cloud storage exfil
- `persistence.py` — systemd, cron, registry, WMI, SSH keys
- `lateral.py` — SSH, WMI, PSExec, SMB, Docker, MSSQL
- `cleanup.py` — Log wiping (journald, auditd, wevtutil)

---

## Configuration

### Main Config (`configs/raphael.yaml`)
```yaml
# API keys, cost control, Tor, Neo4j, etc.
```

### Harness Config (`configs/harness.yaml`)
```yaml
target_host: "127.0.0.1"
target_port: 443
stealth_level: "maximum"
enable_log_suppression: true
enable_etw_patch: true
enable_amsi_patch: true
```

---

## Safety & Legal

⚠️ **FOR AUTHORIZED SECURITY TESTING ONLY**

- Must have written permission from target system owner
- Comply with all applicable laws (CFAA, Computer Misuse Act, etc.)
- Never use against systems you don't own or have explicit permission to test
- All operations include anti-forensic cleanup
- Emergency kill switch integrated

---

## Verification

```bash
# Verify all imports
python3 verify_imports.py

# Run test suite
pytest tests/ -v

# Test CLI
raphael --help
raphael list-exploits
raphael generate-key
```

---

## SSH Key for Repository Access

```bash
# Private key: ~/.ssh/id_ed25519_black
# Public key:  ~/.ssh/id_ed25519_black.pub
# Fingerprint: SHA256:IAG15POUhvEjvHl+jjEhscCQVduHNP3lgugKl46viIg

# Add to GitHub: Settings → SSH and GPG keys → New SSH key
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMgxo9CdkPOADoKa70H2MjDCMniRDdWDec2R/9dDUpSh blackbuilder@raphael.black
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: cryptography` | `pip install cryptography` |
| `ModuleNotFoundError: fastapi` | `pip install fastapi uvicorn python-multipart` |
| `ModuleNotFoundError: httpx` | `pip install httpx` |
| `nmap not found` | `sudo apt-get install nmap` |
| `cloakbrowser not found` | `pip install cloakbrowser && python3 -m cloakbrowser install` |
| Playwright missing | `python3 -m playwright install chromium` |
| SSH permission denied | Add SSH key to GitHub, ensure `ssh-agent` running |

---

## License

MIT License — See LICENSE file (if present) or pyproject.toml

---

*Raphael_Black v3.1 — Maximum attack power. Maximum stealth. Zero Docker.*