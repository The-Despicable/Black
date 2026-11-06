"""raphael-ma-tui — Textual mission console for the raphael-ma multi-agent CLI.

This package is a *wrapper*: it drives the existing Typer command surface of
``raphael.multiagent.cli`` in-process and never re-implements business logic.
See ``engine.py`` for the single import seam.
"""

from __future__ import annotations


def run() -> None:
    """Console entry point (``raphael-ma-tui``)."""
    from .app import main

    main()


__all__ = ["run"]
