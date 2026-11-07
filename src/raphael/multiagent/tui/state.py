"""TUI-side application state.

Everything here is *presentation* state: home path, mock/live arming,
verbosity, cached facts read from the documented data locations
(config.yaml, transcripts/, audit log).  No business logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

DEFAULT_HOME = "~/.raphael/ma"


@dataclass
class AppState:
    home: Optional[str] = None
    armed_live: bool = False          # mock by default; live only when armed
    verbose: bool = False
    busy: bool = False
    config_mode: Optional[str] = None
    governance: Dict[str, Any] = field(default_factory=dict)
    engine_ok: Optional[bool] = None
    engine_path: Optional[str] = None
    engine_error: Optional[str] = None
    last_result: Optional[Any] = None  # engine.RunResult, avoids import cycle
    brain_summary: Optional[str] = None  # one-line brain facts for the status strip
                                         # (set by the brain screen from `brain status`)

    def __post_init__(self) -> None:
        if self.home is None:
            self.home = os.environ.get("RAPHAEL_MA_HOME") or DEFAULT_HOME
        self.home = str(Path(self.home).expanduser())
        self.load_config()

    # ---- documented data locations ------------------------------------
    @property
    def home_path(self) -> Path:
        return Path(self.home)

    @property
    def config_path(self) -> Path:
        return self.home_path / "config.yaml"

    @property
    def db_path(self) -> Path:
        return self.home_path / "brain.db"

    def load_config(self) -> None:
        """Read home/config.yaml (documented location) for mode + governance."""
        self.config_mode = None
        self.governance = {}
        try:
            raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(raw, dict):
            mode = raw.get("mode")
            self.config_mode = str(mode) if mode is not None else None
            gov = raw.get("governance")
            if isinstance(gov, dict):
                self.governance = gov

    # ---- governance display facts (read-only) -------------------------
    @property
    def governance_type(self) -> str:
        g = self.governance
        if not g:
            return "null"
        t = g.get("type")
        if isinstance(t, str) and t:
            return t
        if g.get("audit_path"):
            return "audit"
        return "custom"

    @property
    def kill_switch(self) -> str:
        return str(self.governance.get("kill_switch") or "")

    @property
    def kill_switch_set(self) -> bool:
        return bool(self.kill_switch)

    @property
    def strict(self) -> bool:
        # CLI default is fail-closed: strict defaults to True when unset.
        return bool(self.governance.get("strict", True))

    @property
    def unrestricted(self) -> bool:
        return self.governance_type == "unrestricted"

    @property
    def audit_path(self) -> str:
        return str(self.governance.get("audit_path") or "")

    # ---- argv helpers ---------------------------------------------------
    def augment(self, argv: List[str], json_mode: bool = False) -> List[str]:
        """Prepend global options exactly as the CLI defines them
        (``raphael-ma --json --verbose <command> ...``)."""
        argv = [str(a) for a in argv]
        pre: List[str] = []
        if json_mode and "--json" not in argv:
            pre.append("--json")
        if self.verbose and "-v" not in argv and "--verbose" not in argv:
            pre.append("--verbose")
        return pre + argv

    def mode_flags(self) -> List[str]:
        """Per-command mode flags: explicit mock unless live is armed."""
        return ["--live"] if self.armed_live else ["--mock"]

    def set_engine(self, ok: bool, path: Optional[str], error: Optional[str]) -> None:
        self.engine_ok = ok
        self.engine_path = path
        self.engine_error = error
