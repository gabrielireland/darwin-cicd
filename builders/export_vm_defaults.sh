#!/bin/bash
set -euo pipefail
# ========================================
# Export Common VM Defaults
# ========================================
# Sets shared environment variables for create_vm.sh.
# Source this BEFORE calling create_vm.sh.
#
# Pipeline-specific variables that must be set BEFORE sourcing:
#   VM_NAME, _MACHINE_TYPE
# Optional (have defaults):
#   STARTUP_SCRIPT (defaults to /tmp/startup-script.sh)
#   DEFAULTS_FILE  - Path to project's defaults.yaml
# ========================================

CICD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${CICD_ROOT}/config/load_defaults.sh"

export STARTUP_SCRIPT="${STARTUP_SCRIPT:-/tmp/startup-script.sh}"
export VM_NAME="${VM_NAME:?Missing VM_NAME}"
export TRAINING_ZONES="${TRAINING_ZONES:-${CB_VM_ZONES}}"
export _MACHINE_TYPE="${_MACHINE_TYPE:?Missing _MACHINE_TYPE}"
export _GPU_TYPE="${_GPU_TYPE:-}"
export _GPU_COUNT="${_GPU_COUNT:-0}"
export _BOOT_DISK_SIZE="${_BOOT_DISK_SIZE:-${CB_BOOT_DISK_SIZE}}"
export _VM_SERVICE_ACCOUNT="${_VM_SERVICE_ACCOUNT:-${CB_VM_SERVICE_ACCOUNT}}"
export _USE_SPOT="${_USE_SPOT:-false}"
