#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
exec "${ROOT}/.venv/bin/python" -m raphael.exploit_factory --help
