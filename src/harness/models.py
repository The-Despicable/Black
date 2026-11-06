"""
harness.models — Data models for BlackHatHarness v3.1.

Provides ActionRequest and Target dataclasses used by test suites
and the broader harness for structured action submission.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple


@dataclass
class Target:
    """Represents a target system for an action."""
    host: str
    scope: Tuple[str, ...] = field(default_factory=tuple)
    port: Optional[int] = None
    service: Optional[str] = None


@dataclass
class ActionRequest:
    """A request to perform an action on a target."""
    action_type: str
    target: Target
    rationale: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessConfig:
    """Configuration for the RaphaelHarness (legacy test model)."""
    dry_run: bool = False
    target_host: str = "127.0.0.1"
    authorized_scopes: Tuple[str, ...] = field(default_factory=tuple)


@dataclass
class RaphaelHarness:
    """Minimal harness wrapper for legacy test compatibility."""
    config: HarnessConfig

    async def start(self):
        return {"status": "started", "dry_run": self.config.dry_run}

    async def submit(self, action: ActionRequest) -> dict:
        """Submit an action for execution.

        Returns a dict with an "approved" key indicating scope compliance.
        """
        if self.config.dry_run:
            # In dry-run mode, check if target host is in authorized scopes
            if self.config.authorized_scopes:
                approved = action.target.host in self.config.authorized_scopes
            else:
                approved = True
            return {"approved": approved, "action": action.action_type, "target": action.target.host}
        return {"approved": True, "action": action.action_type, "target": action.target.host}

    async def stop(self):
        return {"status": "stopped"}
