"""Portable shim: re-export the repo's ``configs.target`` surface.

Historically this inserted a hardcoded ``/home/yaser/raphael-2.0`` into
``sys.path`` and imported ``config.target`` — a path that only existed on
the original author's machine. The package lives at the repository root
as ``configs``; derive that location from this file instead so the shim
works from any checkout.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]  # src/orchestrator/config -> repo root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from configs.target import *  # noqa: F401, F403, E402
