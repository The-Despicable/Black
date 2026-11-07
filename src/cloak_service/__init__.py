"""CloakBrowser stealth web-research service.

Packaged because ``pyproject.toml`` declares ``cloak_service*`` in
``[tool.setuptools.packages.find].include`` and
``orchestrator.agents.recon`` imports ``cloak_service.cloakbrowser`` for
web fingerprinting. Without this marker the package was importable from a
source checkout (PEP 420 namespace package) but silently omitted from a
built wheel.
"""
