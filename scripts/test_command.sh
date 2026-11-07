#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
exec "${ROOT}/.venv/bin/python" -m raphael.verifier --help 2>&1 | head -40
