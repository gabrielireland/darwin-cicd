#!/bin/bash
# ========================================
# Load Shared Defaults from defaults.yaml
# ========================================
# Parses defaults.yaml and exports all values as CB_ prefixed env vars.
# Pure bash - no yq/jq dependency.
#
# Usage (set DEFAULTS_FILE to your project's defaults.yaml):
#   export DEFAULTS_FILE="path/to/defaults.yaml"
#   source cicd/config/load_defaults.sh
#
# After sourcing:
#   CB_REGION, CB_BUCKET, CB_SERVICE_ACCOUNT, CB_VM_ZONES, etc.
#
# Override: CloudBuild substitution variables (_VAR) take precedence
# when checked by the calling script.
# ========================================
set -euo pipefail

# Find defaults.yaml relative to this script
_LOAD_DEFAULTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULTS_FILE="${DEFAULTS_FILE:-${_LOAD_DEFAULTS_DIR}/defaults.yaml}"

if [[ ! -f "$DEFAULTS_FILE" ]]; then
  echo "ERROR: Defaults file not found: $DEFAULTS_FILE" >&2
  exit 1
fi

while IFS= read -r line; do
  # Skip comments and empty lines
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line// }" ]] && continue
  # Skip lines without a colon (not key: value)
  [[ "$line" != *":"* ]] && continue

  # Extract key (before first colon) and value (after first colon)
  key=$(echo "$line" | cut -d':' -f1 | xargs)
  value=$(echo "$line" | cut -d':' -f2- | xargs | sed "s/^['\"]//;s/['\"]$//")

  [[ -z "$key" ]] && continue

  # Convert to uppercase with CB_ prefix: vm_zones -> CB_VM_ZONES
  var_name="CB_$(echo "$key" | tr '[:lower:]' '[:upper:]' | tr '-' '_')"

  export "$var_name"="$value"
done < "$DEFAULTS_FILE"
