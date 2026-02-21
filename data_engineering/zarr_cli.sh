#!/bin/bash
# ========================================
# Zarr Data Engineering CLI (Shell Entry Point)
# ========================================
# Usage:
#   bash cicd/data_engineering/zarr_cli.sh create --schema schema.json --output out.zarr
#   bash cicd/data_engineering/zarr_cli.sh validate --schema schema.json --zarr out.zarr --strict
# ========================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: python3 is required to run zarr_cli.sh" >&2
  exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/zarr_cli.py" "$@"
