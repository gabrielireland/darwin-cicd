#!/bin/bash
# ========================================
# Run Contract CLI (Shell Entry Point)
# ========================================
# Usage:
#   bash cicd/utils/run_contract.sh init ...
#   bash cicd/utils/run_contract.sh finalize ...
# ========================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: python3 is required to run run_contract.sh" >&2
  exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/run_contract.py" "$@"
