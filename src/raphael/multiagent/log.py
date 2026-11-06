"""Structured logging for raphael-ma.

Levels come from, in order of precedence:
1. the --verbose/-v CLI flag (forces DEBUG)
2. the RAPHAEL_MA_LOG env var (debug | info | warning | error)
3. default: WARNING (quiet in normal use; nothing on success paths)

Log records go to stderr so stdout stays clean for piping; Rich output is
unaffected. Use `get_logger("cli")`, `get_logger("ui")`, ... from any module.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Dict

ROOT_LOGGER = "raphael-ma"
_LEVELS: Dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}
DEFAULT_LEVEL = logging.WARNING


def resolve_level(verbose: bool = False) -> int:
    """--verbose wins over RAPHAEL_MA_LOG wins over the default."""
    env = os.environ.get("RAPHAEL_MA_LOG", "").strip().lower()
    if env in _LEVELS:
        return _LEVELS[env]
    return logging.DEBUG if verbose else DEFAULT_LEVEL


def configure_logging(verbose: bool = False) -> None:
    """(Re)install the raphael-ma handler. Safe to call repeatedly (tests do)."""
    level = resolve_level(verbose)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s", "%H:%M:%S")
    )
    root = logging.getLogger(ROOT_LOGGER)
    root.handlers[:] = [handler]
    root.setLevel(level)
    # we emit through our own handler; stop records from re-appearing on the
    # root logger's handlers (propagation bypasses ancestor *logger* levels)
    root.propagate = False
    root.debug("logging configured at level %s", logging.getLevelName(level))


def get_logger(name: str = "") -> logging.Logger:
    """Return a logger under the raphael-ma namespace.

    get_logger()            -> 'raphael-ma'
    get_logger('cli')       -> 'raphael.multiagent.cli'
    get_logger('raphael.multiagent.ui')  -> 'raphael.multiagent.ui'  (already-qualified names pass through)
    """
    if not name:
        return logging.getLogger(ROOT_LOGGER)
    if name == "__main__" or not name.startswith("raphael-ma"):
        return logging.getLogger(f"{ROOT_LOGGER}.{name}")
    return logging.getLogger(name)
