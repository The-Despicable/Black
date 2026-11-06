# Raphael Black Hat Harness v3.0

**Maximum attack power. Maximum stealth. Zero Docker dependency.**

## What Changed

The `Raphael_RedTeam` repo has been restructured from a Docker-based microservices architecture into a **native Python single-package deployment** powered by the **Black Hat Harness**.

### Removed (Docker migration)
- All `Dockerfile`, `docker-compose.yml`, `Dockerfile.sandbox` files
- `docker/` directory
- Containerized service orchestration
- All Docker network/volume dependencies

### Added (Black Hat Harness)
- `src/harness/black_hat_core.py` — Anti-forensic exploitation engine (memory-resident, log suppression, ETW/AMSI patching, secure deletion, timestomping, database exploitation)
- `src/harness/ltad_engine.py` — Live Target Adaptive Exploitation (LTAE) engine with real-time state machine, behavioral baselining, WAF/IPS detection, deception scoring, adaptive evasion, polymorphic payloads
- `src/harness/php2shell.py` — PHP2Shell webshell implantation framework with 10 polymorphic variants, filter chains, and persistence
- `src/harness/ai_exploit_generator.py` — AI-driven exploit research & evolution using CloakBrowser + LLM genetic algorithm
- `src/harness/black_hat_cli.py` — Unified CLI entry point
- `src/cloak-service/cloakbrowser.py` — Fixed CloakBrowser integration (real Playwright launcher, not broken httpx stub)
- `src/cloak-service/main.py` — Fixed FastAPI service on port 3401 with research endpoints (`/research`, `/browse`, `/screenshot`, `/interact`, `/identities`, `/health`)
- `install.sh` — Native installer (no Docker)

## Architecture

```
Raphael Black Hat Harness
├── BlackHatHarness (core orchestrator)
│   ├── StealthEngine (ETW/AMSI patching, memory zeroing)
│   ├── MemoryResidentExecutor (Donut/PEzor fileless execution)
│   ├── LogSuppressor (Invoke-Phant0m, auditpol, log clearing)
│   ├── NetworkCloak (JA3 spoofing, domain fronting, data exfiltration)
│   ├── DatabaseExploiter (direct MySQL/PostgreSQL/MSSQL protocols)
│   └── AntiForensicCleanup (secure delete, timestomp, free space wipe)
├── LiveTargetEngine (LTAE — live target state machine)
├── PHP2ShellExploiter (polymorphic PHP webshells)
├── ExploitGenerator (AI research + genetic evolution)
└── CloakBrowser (stealth web research: Sci-Hub, ArXiv, Exploit-DB, GitHub)
```

## Installation

```bash
# Clone and install (zero Docker)
./install.sh

# Or manually
python3 -m pip install --user -e .
python3 -m cloakbrowser install
python3 -m playwright install chromium
```

## Usage

### 1. Full black hat operation
```bash
python3 -m harness.black_hat_cli exploit \
  --target 192.168.1.100 \
  --port 443 \
  --os windows \
  --stealth maximum \
  --objective ops/objective.json
```

### 2. Broad internet vulnerability scan
```bash
python3 -m harness.black_hat_cli scan \
  --target 10.0.0.0/24 \
  --ports 1-1000
```

### 3. Live target adaptive exploitation
```bash
python3 -m harness.black_hat_cli exploit-live \
  --host 192.168.1.100 \
  --port 80
```

### 4. PHP2Shell webshell implantation
```bash
python3 -m harness.black_hat_cli php2shell \
  --target-url http://target/upload.php \
  --upload-point http://target/upload.php \
  --lfi-param page
```

### 5. Research via CloakBrowser (Sci-Hub, ArXiv, Exploit-DB, GitHub)
```bash
python3 -m harness.black_hat_cli research \
  --query "CVE-2024-XXXX" \
  --sources scihub,exploitdb \
  --download-pdfs
```

### 6. AI-driven exploit generation
```bash
python3 -m harness.black_hat_cli ai-generate \
  --target 192.168.1.100 \
  --vuln-type sqli \
  --cycles 15 \
  --mutation-rate 0.3
```

## Stealth Features

| Feature | Implementation |
|---------|---------------|
| Memory-resident execution | Donut + PEzor + direct syscalls |
| ETW patching | NtEtwEventWrite → `ret` |
| AMSI patching | AmsiScanBuffer → `xor eax,eax; ret` |
| Log suppression | Invoke-Phant0m thread termination + auditpol disable |
| Event log clearing | wevtutil cl (Windows), shred (Linux) |
| Timestomping | Match MAC times to reference file |
| Secure deletion | sdelete (Windows), shred -zu (Linux) |
| Free space wipe | cipher /w (Windows) |
| JA3 spoofing | Chrome/Firefox TLS fingerprint profiles |
| Domain fronting | Configurable CDN fronting domain |
| Fingerprint rotation | User-Agent, viewport, canvas, WebGL, audio |
| Proxy chains | Tor SOCKS5 support |
| Payload polymorphism | Fernet encryption + random decoder stubs |
| PHP webshell polymorphism | 10 variants, string splitting, dead code, variable renaming |

## System Requirements

- Python 3.9+
- Playwright (Chromium browser)
- CloakBrowser package
- Optional system tools: nmap, sqlmap, hydra, metasploit, crackmapexec, chisel, tor

## Anti-Forensic Warning

This tool is designed for **authorized security testing only**. All operations include anti-forensic cleanup. Use only on systems you own or have explicit written authorization to test.
