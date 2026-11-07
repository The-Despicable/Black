"""raphael-ma - a self-evolving multi-agent CLI.

Debates, communities, model teams and a persistent thinking brain.
"""
from __future__ import annotations

try:  # installed package metadata is the source of truth (pyproject: 3.1.0)
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    __version__ = _pkg_version("raphael-black")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "3.1.0"
APP_NAME = "raphael-ma"
