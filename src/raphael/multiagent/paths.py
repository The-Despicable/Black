"""Filesystem path resolution for raphael-ma state.

Order of precedence:
1. $RAPHAEL_MA_HOME            (explicit override, used by tests/CI)
2. --home flag / config   (handled in config.py)
3. ~/.raphael/ma               (default)
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIRNAME = ".raphael/ma"


def default_home() -> Path:
    env = os.environ.get("RAPHAEL_MA_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / APP_DIRNAME


def home_from_config(cfg_value) -> Path:
    if cfg_value:
        return Path(str(cfg_value)).expanduser().resolve()
    return default_home()


def ensure_home(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    return home


def validate_home_path(path: Path) -> Path:
    """Normalize and sanity-check a user-supplied raphael-ma home directory.

    Rejects the filesystem root, paths that already exist as files, and
    relative paths that escape to something unusable. Returns the resolved
    absolute path; raises ValueError with a human-readable reason otherwise.
    """
    resolved = Path(path).expanduser().resolve()
    if resolved == Path(resolved.anchor):  # "/" (or "C:\\" on Windows)
        raise ValueError("refusing to use the filesystem root as raphael-ma home")
    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"path exists and is not a directory: {resolved}")
    if not resolved.is_absolute():  # defensive; resolve() normally guarantees this
        raise ValueError(f"path is not absolute after resolution: {resolved}")
    return resolved


def config_path(home: Path) -> Path:
    return home / "config.yaml"


def db_path(home: Path) -> Path:
    return home / "brain.db"
