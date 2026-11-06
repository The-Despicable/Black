"""
conftest.py — v3.1 Test Infrastructure
Ensures pytest can import all modules from repo root without hard-coded paths.
"""

import sys
from pathlib import Path

# Get the repository root (parent of conftest.py)
REPO_ROOT = Path(__file__).resolve().parent
SRC_PATH = REPO_ROOT / "src"

# Add src to Python path for all test collections (avoids hard-coded absolute paths)
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Also add repo root for scripts imports (e.g., scripts.JUDGE)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
