#!/usr/bin/env bash
"""
Raphael Black Hat Harness v3.1 — Installation Script

Detects platform and installs appropriate dependencies.
Zero Docker dependency — native Python only.
"""

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM="$(uname -s)"

echo "=== Raphael Black Hat Harness v3.1 Installer ==="
echo "Platform: $PLATFORM"

# Detect Python
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "ERROR: Python 3 not found"
    exit 1
fi

echo "Using Python: $($PYTHON --version)"

# Install Python dependencies
echo "Installing core Python dependencies..."
$PYTHON -m pip install --upgrade pip setuptools wheel

echo "Installing raphael-black package (editable)..."
$PYTHON -m pip install -e "$SCRIPT_DIR"

# Install optional dependencies based on platform
echo "Installing optional dependencies..."

case "$PLATFORM" in
    Linux*)
        echo "Linux detected — installing system tools..."
        if command -v apt-get &>/dev/null; then
            sudo apt-get update -y
            sudo apt-get install -y \
                coreutils wipe bleachbit iodine obfs4proxy tor steghide \
                chkrootkit rkhunter lynis auditd unhide tcplay
        fi
        ;;
    Darwin*)
        echo "macOS detected — install tools via brew:"
        echo "  brew install wipe steghide tor"
        ;;
    CYGWIN*|MINGW*|Windows*)
        echo "Windows detected — install tools manually:"
        echo "  - Sysinternals Suite (sdelete, etc.)"
        echo "  - Donut (shellcode generator)"
        echo "  - PEzor (PE obfuscation)"
        ;;
esac

# Install Python extras
echo "Installing Python extras..."
$PYTHON -m pip install cryptography aiohttp pydantic

# Create logs directory
mkdir -p "$SCRIPT_DIR/logs"

echo ""
echo "=== Installation Complete ==="
echo "Run: raphael --help"
echo "Or:  $PYTHON -m harness.black_hat_cli --help"
echo ""
echo "WARNING: This tool requires explicit authorization. See docs/SAFETY.md"
