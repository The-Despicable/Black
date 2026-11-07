"""REST endpoints for pentest tools execution."""

import asyncio
import logging
import shlex
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from orchestrator.api.types import (
    ToolExecuteRequest,
    ToolExecuteResponse,
    ToolListResponse,
    ToolInfo,
    Persona,
    check_tool_permission,
)
from orchestrator.auth import require_scope
from orchestrator.chains.tool_registry import (
    execute_nmap,
    execute_sqlmap,
    execute_bloodhound,
    execute_metasploit,
    execute_crackmapexec,
    execute_chisel,
    ToolRegistry,
)
from orchestrator.audit_trail import record_event

logger = logging.getLogger("tools_api")

router = APIRouter(prefix="/api/tools", tags=["tools"])

# Tool metadata for listing
TOOL_METADATA = [
    ToolInfo(
        name="nmap",
        description="Network port scanning and service enumeration",
        category="recon",
        parameters={
            "target": {"type": "string", "description": "Target IP, domain, or CIDR"},
            "ports": {"type": "string", "description": "Port range (e.g., '1-65535', '80,443,8080')", "default": "1-1000"},
            "scan_type": {"type": "string", "description": "Scan type: syn, connect, udp, ack", "default": "syn"},
            "stealth": {"type": "boolean", "description": "Use stealth timing (T2)", "default": False},
            "aggressive": {"type": "boolean", "description": "Aggressive scan (-A)", "default": False},
            "service_version": {"type": "boolean", "description": "Service version detection (-sV)", "default": True},
            "os_detection": {"type": "boolean", "description": "OS detection (-O)", "default": False},
            "scripts": {"type": "string", "description": "NSE scripts to run", "default": "default"},
        },
        requires_approval=True,
    ),
    ToolInfo(
        name="sqlmap",
        description="Automated SQL injection detection and exploitation",
        category="exploit",
        parameters={
            "url": {"type": "string", "description": "Target URL with vulnerable parameter"},
            "data": {"type": "string", "description": "POST data for testing"},
            "dbms": {"type": "string", "description": "Force DBMS (mysql, postgres, mssql, oracle, sqlite)"},
            "level": {"type": "integer", "description": "Test level (1-5)", "default": 3},
            "risk": {"type": "integer", "description": "Risk level (1-3)", "default": 2},
            "batch": {"type": "boolean", "description": "Non-interactive mode", "default": True},
            "threads": {"type": "integer", "description": "Number of threads", "default": 5},
            "timeout": {"type": "integer", "description": "Request timeout in seconds", "default": 30},
        },
        requires_approval=True,
    ),
    ToolInfo(
        name="bloodhound",
        description="Active Directory attack path analysis via BloodHound",
        category="postex",
        parameters={
            "domain": {"type": "string", "description": "AD domain (e.g., corp.local)"},
            "dc": {"type": "string", "description": "Domain controller IP/hostname"},
            "username": {"type": "string", "description": "Username for authentication"},
            "password": {"type": "string", "description": "Password for authentication"},
            "collection_method": {"type": "string", "description": "Collection method: all, group, localadmin, session, trust, dc", "default": "all"},
            "output_dir": {"type": "string", "description": "Output directory for JSON files"},
            "stealth": {"type": "boolean", "description": "Use stealth collection", "default": False},
        },
        requires_approval=True,
    ),
    ToolInfo(
        name="metasploit",
        description="Metasploit Framework module execution",
        category="exploit",
        parameters={
            "module": {"type": "string", "description": "Module path (e.g., exploit/windows/smb/ms17_010_eternalblue)"},
            "rhost": {"type": "string", "description": "Target host"},
            "rport": {"type": "integer", "description": "Target port"},
            "payload": {"type": "string", "description": "Payload to use (e.g., windows/x64/meterpreter/reverse_tcp)"},
            "lhost": {"type": "string", "description": "Local host for reverse connection"},
            "lport": {"type": "integer", "description": "Local port for reverse connection", "default": 4444},
            "options": {"type": "object", "description": "Additional module options as key-value pairs"},
        },
        requires_approval=True,
    ),
    ToolInfo(
        name="crackmapexec",
        description="Network enumeration and credential testing across protocols",
        category="postex",
        parameters={
            "target": {"type": "string", "description": "Target IP, CIDR, or file with targets"},
            "protocol": {"type": "string", "description": "Protocol: smb, ssh, winrm, ldap, mssql, rdp", "default": "smb"},
            "username": {"type": "string", "description": "Username or user file"},
            "password": {"type": "string", "description": "Password, hash, or pass file"},
            "hash": {"type": "string", "description": "NTLM hash for pass-the-hash"},
            "command": {"type": "string", "description": "Command to execute on target"},
            "module": {"type": "string", "description": "CME module to run"},
            "options": {"type": "object", "description": "Module options as key-value pairs"},
        },
        requires_approval=True,
    ),
    ToolInfo(
        name="chisel",
        description="Fast TCP/UDP tunneling over HTTP/SOCKS5",
        category="c2",
        parameters={
            "mode": {"type": "string", "description": "Mode: server or client", "default": "client"},
            "target": {"type": "string", "description": "Target server (host:port) for client mode"},
            "port": {"type": "integer", "description": "Local port to bind (server mode)", "default": 8080},
            "socks5": {"type": "boolean", "description": "Enable SOCKS5 proxy", "default": True},
            "reverse": {"type": "boolean", "description": "Reverse tunnel (R:remote:local)", "default": False},
            "auth": {"type": "string", "description": "Authentication string (user:pass)"},
            "fingerprint": {"type": "string", "description": "TLS fingerprint for server verification"},
        },
        requires_approval=True,
    ),
    # Black Hat Harness tools
    ToolInfo(
        name="php2shell",
        description="PHP2Shell polymorphic webshell implantation",
        category="exploit",
        parameters={
            "url": {"type": "string", "description": "Target URL (e.g., http://target.com)"},
            "upload_point": {"type": "string", "description": "File upload endpoint URL", "default": None},
            "lfi_param": {"type": "string", "description": "LFI parameter name", "default": None},
            "rfi_param": {"type": "string", "description": "RFI parameter name", "default": None},
        },
        requires_approval=True,
    ),
    ToolInfo(
        name="ltad_exploit",
        description="Live Target Adaptive Exploitation (LTAE)",
        category="exploit",
        parameters={
            "target": {"type": "string", "description": "Target host"},
            "port": {"type": "integer", "description": "Target port", "default": 443},
            "probe_types": {"type": "array", "description": "Probe types: sqli, xss, cmd_injection, path_traversal", "default": ["sqli", "xss", "cmd_injection", "path_traversal"]},
            "payload": {"type": "string", "description": "Probe payload", "default": "test_probe"},
        },
        requires_approval=True,
    ),
    ToolInfo(
        name="memory_resident",
        description="Memory-resident payload execution (Donut/PEzor)",
        category="exploit",
        parameters={
            "target": {"type": "string", "description": "Target host"},
            "port": {"type": "integer", "description": "Target port", "default": 443},
            "binary_path": {"type": "string", "description": "Path to binary to convert to shellcode", "default": None},
            "target_pid": {"type": "integer", "description": "Target PID for injection", "default": None},
        },
        requires_approval=True,
    ),
    ToolInfo(
        name="php_filter_chain",
        description="PHP filter chain exploitation (php://filter)",
        category="exploit",
        parameters={
            "url": {"type": "string", "description": "Target URL"},
            "lfi_param": {"type": "string", "description": "LFI parameter name", "default": "file"},
        },
        requires_approval=True,
    ),
]


@router.get("", response_model=ToolListResponse)
async def list_tools(
    category: Optional[str] = Query(None, description="Filter by category"),
    persona: Persona = Query(Persona.Z3R0, description="Persona for permission filtering"),
    auth=Depends(require_scope("tools:read")),
):
    """List available tools with persona-based permission info."""
    tools = TOOL_METADATA
    
    if category:
        tools = [t for t in tools if t.category == category]
    
    # Add permission info per persona
    result_tools = []
    for tool in tools:
        allowed, needs_approval = check_tool_permission(persona, tool.name, "default")
        tool_dict = tool.model_dump()
        tool_dict["allowed_for_persona"] = allowed
        tool_dict["requires_approval"] = needs_approval or tool.requires_approval
        result_tools.append(ToolInfo(**tool_dict))
    
    return ToolListResponse(tools=result_tools, total=len(result_tools))


@router.post("/{tool_name}", response_model=ToolExecuteResponse)
async def execute_tool(
    tool_name: str,
    req: ToolExecuteRequest,
    auth=Depends(require_scope("tools:execute")),
):
    """Execute a pentest tool with given parameters."""
    execution_id = str(uuid.uuid4())
    
    # Validate tool exists
    tool_meta = next((t for t in TOOL_METADATA if t.name == tool_name), None)
    if not tool_meta:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    
    # Check persona permission
    persona = req.persona or Persona.Z3R0
    allowed, needs_approval = check_tool_permission(persona, tool_name, req.mode or "default")
    
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Tool '{tool_name}' not allowed for persona '{persona.value}' in mode '{req.mode or 'default'}'"
        )
    
    if needs_approval and not req.approved:
        raise HTTPException(
            status_code=403,
            detail=f"Tool '{tool_name}' requires operator approval for persona '{persona.value}'"
        )
    
    # Scope check for target
    target = req.params.get("target") or req.params.get("url") or req.params.get("rhost") or req.params.get("domain")
    if target:
        from orchestrator.scope import default_scope
        if not default_scope.check(target):
            raise HTTPException(
                status_code=403,
                detail=f"Target {target} is not in allowed scope"
            )
    
    record_event(
        action="tool_execute",
        target=target or "unknown",
        phase="api",
        verdict="started",
        metadata={
            "execution_id": execution_id,
            "tool": tool_name,
            "persona": persona.value,
            "mode": req.mode or "default",
            "approved": req.approved,
        }
    )
    
    try:
        # Execute the tool
        # Merge top-level target into params for executor
        exec_params = dict(req.params)
        if req.target:
            exec_params["target"] = req.target
        result = await _execute_tool_by_name(tool_name, exec_params, execution_id)
        
        record_event(
            action="tool_execute",
            target=target or "unknown",
            phase="api",
            verdict="completed" if result.get("success") else "failed",
            metadata={
                "execution_id": execution_id,
                "tool": tool_name,
                "exit_code": result.get("exit_code"),
                "duration": result.get("duration"),
            }
        )
        
        return ToolExecuteResponse(
            execution_id=execution_id,
            tool=tool_name,
            success=result.get("success", False),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
            exit_code=result.get("exit_code", -1),
            duration=result.get("duration", 0),
            artifacts=result.get("artifacts", []),
        )
        
    except Exception as e:
        logger.exception(f"Tool execution failed: {e}")
        record_event(
            action="tool_execute",
            target=target or "unknown",
            phase="api",
            verdict="error",
            metadata={"execution_id": execution_id, "tool": tool_name, "error": str(e)}
        )
        return ToolExecuteResponse(
            execution_id=execution_id,
            tool=tool_name,
            success=False,
            stdout="",
            stderr=str(e),
            exit_code=-1,
            duration=0,
            artifacts=[],
        )


async def _execute_tool_by_name(tool_name: str, params: dict, execution_id: str) -> dict:
    """Route to appropriate tool executor."""
    executors = {
        "nmap": execute_nmap,
        "sqlmap": execute_sqlmap,
        "bloodhound": execute_bloodhound,
        "metasploit": execute_metasploit,
        "crackmapexec": execute_crackmapexec,
        "chisel": execute_chisel,
        # Black Hat Harness executors
        "php2shell": execute_php2shell,
        "ltad_exploit": execute_ltad_exploit,
        "memory_resident": execute_memory_resident,
        "php_filter_chain": execute_php_filter_chain,
    }
    
    executor = executors.get(tool_name)
    if not executor:
        return {"success": False, "stderr": f"No executor for tool: {tool_name}", "exit_code": -1, "duration": 0}
    
    return await executor(params, execution_id)


# Convenience endpoints for common tool invocations
@router.post("/nmap/scan")
async def nmap_quick_scan(
    target: str,
    ports: str = "1-1000",
    stealth: bool = False,
    auth=Depends(require_scope("tools:execute")),
):
    """Quick nmap scan endpoint."""
    req = ToolExecuteRequest(
        target=target,
        params={"target": target, "ports": ports, "stealth": stealth},
        persona=Persona.Z3R0,
    )
    return await execute_tool("nmap", req, auth)


@router.post("/sqlmap/scan")
async def sqlmap_quick_scan(
    url: str,
    data: Optional[str] = None,
    auth=Depends(require_scope("tools:execute")),
):
    """Quick SQLMap scan endpoint."""
    req = ToolExecuteRequest(
        target=url,
        params={"url": url, "data": data, "batch": True},
        persona=Persona.GHOST,  # SQLMap requires Ghost persona
    )
    return await execute_tool("sqlmap", req, auth)


@router.post("/crackmapexec/enum")
async def cme_enum(
    target: str,
    protocol: str = "smb",
    username: str = "",
    password: str = "",
    auth=Depends(require_scope("tools:execute")),
):
    """Quick CrackMapExec enumeration."""
    req = ToolExecuteRequest(
        target=target,
        params={"target": target, "protocol": protocol, "username": username, "password": password},
        persona=Persona.GHOST,
    )
    return await execute_tool("crackmapexec", req, auth)


# ============================================================
# Black Hat Harness Executors
# ============================================================

try:
    from harness.black_hat_core import BlackHatHarness, BlackHatConfig
    from harness.ltad_engine import LiveTargetEngine
    from harness.php2shell import PHP2ShellExploiter
    BH_API_AVAILABLE = True
except ImportError:
    BH_API_AVAILABLE = False


async def execute_php2shell(params: dict, execution_id: str) -> dict:
    """Execute PHP2Shell webshell implantation."""
    if not BH_API_AVAILABLE:
        return {"success": False, "stderr": "Black Hat Harness not available", "exit_code": -1, "duration": 0}
    url = params.get("url", "")
    if not url:
        return {"success": False, "stderr": "url required", "exit_code": -1, "duration": 0}
    try:
        exploiter = PHP2ShellExploiter()
        result = await exploiter.exploit(
            url,
            upload_point=params.get("upload_point"),
            lfi_param=params.get("lfi_param"),
            rfi_param=params.get("rfi_param"),
        )
        return {
            "success": result.get("success", False),
            "stdout": json.dumps(result) if result.get("success") else "",
            "stderr": result.get("error", "") if not result.get("success") else "",
            "exit_code": 0 if result.get("success") else 1,
            "duration": 0,
            "artifacts": [{"type": "php2shell_result", "data": result}],
            "metadata": {"url": url, "method": result.get("method")},
        }
    except Exception as e:
        return {"success": False, "stderr": str(e), "exit_code": -1, "duration": 0}


async def execute_ltad_exploit(params: dict, execution_id: str) -> dict:
    """Execute Live Target Adaptive Exploitation."""
    if not BH_API_AVAILABLE:
        return {"success": False, "stderr": "Black Hat Harness not available", "exit_code": -1, "duration": 0}
    target = params.get("target", "")
    if not target:
        return {"success": False, "stderr": "target required", "exit_code": -1, "duration": 0}
    try:
        import json
        port = int(params.get("port", 443))
        probe_types = params.get("probe_types", ["sqli", "xss", "cmd_injection", "path_traversal"])
        payload = params.get("payload", "test_probe")
        engine = LiveTargetEngine()
        t = await engine.initialize_live_target(target, port)
        results = []
        for pt in probe_types:
            r = await engine.adaptive_probe(t, probe_type=pt, payload=payload)
            results.append(r)
        return {
            "success": True,
            "stdout": json.dumps(results),
            "stderr": "",
            "exit_code": 0,
            "duration": 0,
            "artifacts": [{"type": "ltad_result", "data": results}],
            "metadata": {"target": target, "port": port, "probes": len(results)},
        }
    except Exception as e:
        return {"success": False, "stderr": str(e), "exit_code": -1, "duration": 0}


async def execute_memory_resident(params: dict, execution_id: str) -> dict:
    """Execute memory-resident payload execution."""
    if not BH_API_AVAILABLE:
        return {"success": False, "stderr": "Black Hat Harness not available", "exit_code": -1, "duration": 0}
    target = params.get("target", "")
    if not target:
        return {"success": False, "stderr": "target required", "exit_code": -1, "duration": 0}
    try:
        import json
        config = BlackHatConfig(target_host=target, target_port=int(params.get("port", 443)))
        harness = BlackHatHarness(config)
        binary_path = params.get("binary_path")
        target_pid = params.get("target_pid")
        if binary_path:
            result = await harness.execute_fileless(binary_path, target_pid=target_pid)
        else:
            result = await harness.memory_resident.prepare()
        return {
            "success": result.get("status") == "success",
            "stdout": json.dumps(result),
            "stderr": result.get("error", "") if result.get("status") != "success" else "",
            "exit_code": 0 if result.get("status") == "success" else 1,
            "duration": 0,
            "artifacts": [{"type": "memory_resident_result", "data": result}],
            "metadata": {"target": target},
        }
    except Exception as e:
        return {"success": False, "stderr": str(e), "exit_code": -1, "duration": 0}


async def execute_php_filter_chain(params: dict, execution_id: str) -> dict:
    """Execute PHP filter chain exploitation."""
    if not BH_API_AVAILABLE:
        return {"success": False, "stderr": "Black Hat Harness not available", "exit_code": -1, "duration": 0}
    url = params.get("url", "")
    if not url:
        return {"success": False, "stderr": "url required", "exit_code": -1, "duration": 0}
    try:
        import json
        exploiter = PHP2ShellExploiter()
        result = await exploiter.exploit(url, lfi_param=params.get("lfi_param", "file"))
        return {
            "success": result.get("success", False),
            "stdout": json.dumps(result) if result.get("success") else "",
            "stderr": result.get("error", "") if not result.get("success") else "",
            "exit_code": 0 if result.get("success") else 1,
            "duration": 0,
            "artifacts": [{"type": "php_filter_chain_result", "data": result}],
            "metadata": {"url": url, "method": result.get("method")},
        }
    except Exception as e:
        return {"success": False, "stderr": str(e), "exit_code": -1, "duration": 0}


# Wire Black Hat Harness executors into the ToolRegistry (avoids circular import)
try:
    from orchestrator.chains.tool_registry import registry as _tool_registry
    _tool_registry.set_executor("php2shell", execute_php2shell)
    _tool_registry.set_executor("ltad_exploit", execute_ltad_exploit)
    _tool_registry.set_executor("memory_resident", execute_memory_resident)
    _tool_registry.set_executor("php_filter_chain", execute_php_filter_chain)
except ImportError:
    pass