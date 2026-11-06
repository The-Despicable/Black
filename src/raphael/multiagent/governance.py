"""Governance seam: audit trail + kill-switch gate for every LLM action.

This module is the single integration point a host system (e.g. the Raphael
Black Hat Harness) needs to implement to bring raphael-ma under its governance.

Design (fail-closed where configured):
- ``check(action, context)`` is called before every round / integration /
  evolution step. A host implementation raises :class:`KillSwitchEngaged`
  to stop the session immediately.
- ``audit(event_dict)`` receives structured events: ``session_start``,
  ``round``, ``session_end``, ``session_aborted``, ``turn_failed``,
  ``evolve``. ``FileAuditGovernance`` appends them as JSON lines — the same
  convention Raphael uses for ``logs/harness_audit.jsonl``.
- Configuration lives in the ``governance:`` config section::

      governance:
        strict: true            # ABSENT or true -> an EMPTY governance section
                                # is an ERROR (GovernanceConfigError, CLI exit 4).
                                # Explicit `strict: false` = standalone allow-mode.
        audit_path: "logs/harness_audit.jsonl"  # "" disables the audit file
        tool_name: "raphael-ma"      # "tool": <name> provenance on every record
   # "" disables the audit file
        kill_switch: "myapp.safety.is_engaged" # "module.attr" import spec;
                                               # callable -> bool. Absent = allow.

- If a kill-switch spec is configured but cannot be imported or is not
  callable, construction **raises**: a misconfigured safety hook must never
  degrade to "allow". (Fail closed.)
- STRICT DEFAULT (v0.3): an empty governance section with ``strict``
  absent or true raises :class:`GovernanceConfigError` (CLI exit 4) —
  nothing is silently allowed. Only an explicit ``strict: false`` keeps
  the historical standalone :class:`NullGovernance` behavior (the
  out-of-box template written by ``raphael-ma init`` sets it explicitly). — standalone raphael-ma stays usable.

Wiring for a host: subclass or duck-type :class:`Governance` and inject it
via ``SessionRunner(cfg, db, registry, ..., governance=MyGovernance())``.
"""
from __future__ import annotations

import datetime as _dt
import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from raphael.multiagent.log import get_logger

log = get_logger("governance")


class KillSwitchEngaged(RuntimeError):
    """Raised by a governance check to abort the session immediately."""


class GovernanceConfigError(ValueError):
    """Governance is unconfigured under strict mode, or misconfigured.

    Raised (never silently degraded to "allow") when:

    - ``governance.strict`` is on (the default when the key is absent) and
      neither ``audit_path`` nor ``kill_switch`` is configured; or
    - a configured ``kill_switch`` spec cannot be imported / is not callable.
    """


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="milliseconds")


@runtime_checkable
class Governance(Protocol):
    def check(self, action: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Gate an action; raise KillSwitchEngaged to stop it."""

    def audit(self, event: Dict[str, Any]) -> None:
        """Record a structured event (never raises into the caller's flow)."""


class NullGovernance:
    """Allow everything; events go to debug logging only (standalone mode)."""

    def check(self, action: str, context: Optional[Dict[str, Any]] = None) -> None:
        log.debug("governance check passed: %s %s", action, context or {})

    def audit(self, event: Dict[str, Any]) -> None:
        log.debug("governance event: %s", event)


class FileAuditGovernance(NullGovernance):
    """Audit events to a JSONL file; optional pluggable kill-switch callable.

    ``tool_name`` is the provenance stamped on every record (``"tool":
    <tool_name>``) so a host deployment can emit ``"tool": "raphael"`` or
    ``"raphael.ma"`` while keeping this exact schema — see
    ``governance.tool_name`` in the config.

    Thread-safe: teams mode audits from worker threads concurrently.
    """

    def __init__(
        self,
        audit_path: Path,
        kill_switch: Optional[Callable[[], bool]] = None,
        tool_name: str = "raphael-ma",
    ):
        self.audit_path = Path(audit_path)
        self.kill_switch = kill_switch
        self.tool_name = str(tool_name or "raphael-ma")
        self._lock = threading.Lock()
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def check(self, action: str, context: Optional[Dict[str, Any]] = None) -> None:
        if self.kill_switch is not None and self.kill_switch():
            raise KillSwitchEngaged(
                f"kill switch engaged before action '{action}'"
                + (f" ({context})" if context else "")
            )
        super().check(action, context)

    def audit(self, event: Dict[str, Any]) -> None:
        record = {"ts": _now(), "tool": self.tool_name, **event}
        line = json.dumps(record, ensure_ascii=False, default=str)
        try:
            with self._lock:
                with self.audit_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError as exc:  # audit must never take the session down
            log.warning("audit write failed (%s): %s", self.audit_path, exc)


def _load_callable(spec: str) -> Callable[[], bool]:
    """Import 'module.path:attr' or 'module.path.attr' -> callable.

    Raises GovernanceConfigError (not silently returning permissive) on
    failure — configured-but-broken governance fails closed.
    """
    module_part, _, attr = spec.partition(":")
    if not attr:
        # allow dotted form "pkg.mod.attr"
        module_part, _, attr = spec.rpartition(".")
    if not module_part or not attr:
        raise GovernanceConfigError(
            f"kill_switch spec must be 'module:attr' or 'module.attr': {spec!r}"
        )
    import importlib

    try:
        mod = importlib.import_module(module_part)
        obj = getattr(mod, attr)
    except (ImportError, AttributeError) as exc:
        raise GovernanceConfigError(
            f"cannot import kill_switch {spec!r}: {exc}"
        ) from exc
    if not callable(obj):
        raise GovernanceConfigError(f"kill_switch {spec!r} resolved to a non-callable")
    return obj


def _strict_flag(value: Any) -> bool:
    """Interpret governance.strict. ABSENT or unreadable -> True (fail closed).

    Only an explicit false/no/off/0 (bool or string) disables strict mode;
    anything else (including garbage) keeps it on.
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "no", "off", "0")
    return True


def get_governance(cfg: Any) -> Governance:
    """Build the governance object from the config's ``governance:`` section.

    STRICT DEFAULTS: when the ``strict`` key is absent (or true, or any
    unreadable value) an EMPTY governance section is a configuration error
    (:class:`GovernanceConfigError`) — nothing is silently allowed. Only an
    explicit ``strict: false`` yields standalone allow-mode. Note that the
    key is deliberately absent from ``DEFAULT_CONFIG``'s merge base, so a
    host config that simply configures ``audit_path``/``kill_switch`` gets
    strict-by-default semantics; the out-of-box template written by
    ``raphael-ma init`` sets ``strict: false`` explicitly for standalone use.

    When ``governance.type`` is set, delegation goes to :func:`build_governance`
    which supports ``type: null | audit | unrestricted``.
    """
    gov_cfg = dict(getattr(cfg, "raw", {}).get("governance") or {})

    # Explicit type field -> use the factory (supports unrestricted mode)
    gov_type = str(gov_cfg.get("type", "")).strip().lower()
    if gov_type:
        return build_governance(getattr(cfg, "raw", {}))

    # Legacy behavior: audit_path / kill_switch / strict
    audit_path = str(gov_cfg.get("audit_path") or "").strip()
    kill_spec = str(gov_cfg.get("kill_switch") or "").strip()
    if not audit_path and not kill_spec:
        if not _strict_flag(gov_cfg.get("strict")):
            return NullGovernance()
        raise GovernanceConfigError(
            "governance is strict (the default) but neither audit_path nor "
            "kill_switch is configured. Standalone use: set 'governance.strict: "
            "false' explicitly in config.yaml. Host deployment: configure "
            "governance.audit_path (e.g. logs/harness_audit.jsonl) and/or "
            "governance.kill_switch (module:attr -> True aborts)."
        )
    tool_name = str(gov_cfg.get("tool_name") or "raphael-ma")
    kill_fn = _load_callable(kill_spec) if kill_spec else None
    if audit_path:
        return FileAuditGovernance(Path(audit_path), kill_switch=kill_fn, tool_name=tool_name)
    # kill switch configured without an audit file: still gate, still audit to debug
    class _GateOnly(NullGovernance):
        def check(self, action, context=None):
            if kill_fn is not None and kill_fn():
                raise KillSwitchEngaged(f"kill switch engaged before action '{action}'")
            super().check(action, context)

    return _GateOnly()


# --------------------------------------------------------------------------
# Unrestricted governance — authorized red-team mode
# --------------------------------------------------------------------------

class UnrestrictedGovernance:
    """Audit-only governance for authorized security testing.

    NEVER blocks actions. Logs everything for post-hoc review.

    WARNING: Only deploy in isolated lab environments with explicit
    written authorization. This mode disables all safety interlocks.

    Activation (config.yaml):

        governance:
          type: unrestricted
          audit_path: logs/redteam_audit.jsonl
    """

    def __init__(
        self,
        audit_path: Optional[str] = None,
        session_tag: Optional[str] = None,
    ):
        self.audit_path = Path(audit_path) if audit_path else None
        if self.audit_path:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)

        self.session_tag = session_tag or _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self._event_buffer: List[Dict[str, Any]] = []
        self._check_count = 0
        self._audit_count = 0

    def check(self, action: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """Always returns True. Logs the check for review."""
        self._check_count += 1

        safe_context = {
            k: (str(v)[:200] + "..." if len(str(v)) > 200 else v)
            for k, v in (context or {}).items()
        }

        self._log("check", {
            "action": action,
            "allowed": True,
            "mode": "unrestricted",
            "check_seq": self._check_count,
            "context": safe_context,
        })

        return True  # Never block

    def audit(self, event: Dict[str, Any]) -> None:
        """Log event without filtering."""
        self._audit_count += 1

        self._log("audit", {
            "seq": self._audit_count,
            **event,
        })

    def _log(self, kind: str, data: Dict[str, Any]) -> None:
        """Internal logging with buffering."""
        record = {
            "ts": _dt.datetime.now().isoformat(timespec="milliseconds"),
            "tool": "raphael-ma",
            "governance": "unrestricted",
            "session_tag": self.session_tag,
            "kind": kind,
            **data,
        }

        self._event_buffer.append(record)

        if self.audit_path:
            try:
                with self.audit_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            except OSError as exc:  # audit failure must not crash the operation
                log.warning("unrestricted audit write failed (%s): %s", self.audit_path, exc)

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def get_event_buffer(self) -> List[Dict[str, Any]]:
        """Return all events this session (for in-memory inspection)."""
        return self._event_buffer.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Return governance statistics."""
        return {
            "mode": "unrestricted",
            "session_tag": self.session_tag,
            "checks_performed": self._check_count,
            "events_audited": self._audit_count,
            "audit_path": str(self.audit_path) if self.audit_path else None,
        }

    def flush(self) -> None:
        """Explicitly flush buffer (no-op for file-backed, clears memory)."""
        if not self.audit_path:
            for event in self._event_buffer:
                print(json.dumps(event, default=str))
        self._event_buffer.clear()

    def __enter__(self) -> "UnrestrictedGovernance":
        self._log("lifecycle", {"event": "governance_start"})
        return self

    def __exit__(self, *exc) -> None:
        self._log("lifecycle", {
            "event": "governance_end",
            "stats": self.get_stats(),
        })
        self.flush()


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def build_governance(raw: Dict[str, Any]) -> Governance:
    """Construct governance from a raw config dict.

    Config schema:

        governance:
          type: null | audit | unrestricted        # default: null
          enabled: bool                             # default: True
          audit_path: str                           # JSONL trail path
          kill_switch: "module:callable"            # audit-only gate
          strict: bool                              # audit only
          session_tag: str                          # unrestricted tag
    """
    gov_cfg = dict(raw.get("governance") or {})
    gov_type = str(gov_cfg.get("type", "null")).strip().lower()

    if gov_type == "null":
        return NullGovernance()

    if gov_type == "audit":
        audit_path = str(gov_cfg.get("audit_path") or "logs/audit.jsonl").strip()
        kill_spec = str(gov_cfg.get("kill_switch") or "").strip()
        strict = bool(gov_cfg.get("strict", True))
        kill_fn = _load_callable(kill_spec) if kill_spec else None
        return FileAuditGovernance(
            Path(audit_path), kill_switch=kill_fn, tool_name=str(gov_cfg.get("tool_name") or "raphael-ma")
        )

    if gov_type == "unrestricted":
        return UnrestrictedGovernance(
            audit_path=gov_cfg.get("audit_path") or None,
            session_tag=gov_cfg.get("session_tag") or None,
        )

    raise ValueError(f"unknown governance type: {gov_type!r}")
