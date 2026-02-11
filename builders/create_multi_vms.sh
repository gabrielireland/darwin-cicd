#!/bin/bash
set -euo pipefail
# ========================================
# Universal Multi-VM Orchestrator
# ========================================
# Creates 1..N VMs from workspace config files.
# Single entry point for ALL pipelines — replaces direct calls to
# prepare_vm_startup.sh + export_vm_defaults.sh + create_vm.sh.
#
# Reads:
#   /workspace/vm_count.txt           - Number of VMs to create
#   /workspace/vm_config_{idx}.env    - KEY=VALUE pairs per VM (idx starts at 1)
#   /workspace/vm_labels_{idx}.txt    - GCP instance labels per VM (optional)
#
# Each KEY=VALUE in vm_config becomes: sed "s|__KEY__|VALUE|g" on startup script.
# Values containing '|' automatically use '#' as sed delimiter.
#
# Special config keys:
#   AREA or VM_SUFFIX  - Used for VM naming and {AREA} placeholder in PIPELINE_TITLE
#
# Required env vars (shared across all VMs):
#   VM_SCRIPT_NAME   - Pipeline VM script filename (e.g., 'training.sh')
#   CODE_IMAGE_NAME  - Docker image name for this pipeline
#   CLOUDBUILD_YAML  - Name of the CloudBuild YAML file
#   PIPELINE_TITLE   - Human-readable title ({AREA} placeholder supported)
#   PROJECT_ID       - GCP project ID
#   SHORT_SHA        - Git commit SHA
#   BUILD_ID         - CloudBuild build ID
#   DEFAULTS_FILE    - Path to project's defaults.yaml
#   _REGION, _BUCKET
#   _MACHINE_TYPE, _BOOT_DISK_SIZE, _VM_SERVICE_ACCOUNT, _USE_SPOT
#   MAX_RUN_DURATION
# ========================================

CICD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VM_COUNT_FILE="/workspace/vm_count.txt"
if [[ ! -f "$VM_COUNT_FILE" ]]; then
  echo "ERROR: $VM_COUNT_FILE not found" >&2
  exit 1
fi
VM_COUNT=$(cat "$VM_COUNT_FILE")

if [[ "$VM_COUNT" -lt 1 ]]; then
  echo "ERROR: vm_count must be >= 1, got $VM_COUNT" >&2
  exit 1
fi

echo ""
echo "=========================================="
echo "Universal VM Orchestrator: $VM_COUNT VM(s)"
echo "=========================================="
echo ""

# Save original PIPELINE_TITLE for per-VM {AREA} resolution
ORIG_PIPELINE_TITLE="${PIPELINE_TITLE}"
ALL_VM_NAMES=""

for IDX in $(seq 1 "$VM_COUNT"); do
  CONFIG_FILE="/workspace/vm_config_${IDX}.env"
  LABELS_FILE="/workspace/vm_labels_${IDX}.txt"

  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: Config file not found: $CONFIG_FILE" >&2
    exit 1
  fi

  # Extract VM suffix (AREA or VM_SUFFIX from config)
  VM_SUFFIX=""
  while IFS= read -r LINE; do
    [[ -z "$LINE" || "$LINE" =~ ^# || "$LINE" != *"="* ]] && continue
    KEY="${LINE%%=*}"
    VALUE="${LINE#*=}"
    if [[ "$KEY" == "AREA" || "$KEY" == "VM_SUFFIX" ]]; then
      VM_SUFFIX="$VALUE"
      break
    fi
  done < "$CONFIG_FILE"
  VM_SUFFIX="${VM_SUFFIX:-vm${IDX}}"

  # Read instance labels
  if [[ -f "$LABELS_FILE" ]]; then
    export INSTANCE_LABELS=$(cat "$LABELS_FILE")
  else
    export INSTANCE_LABELS="type=vm,build=${SHORT_SHA:-unknown}"
  fi

  # Build VM name from CODE_IMAGE_NAME + suffix + timestamp
  VM_PREFIX=$(echo "$CODE_IMAGE_NAME" | tr '_' '-')
  export VM_NAME="${VM_PREFIX}-${VM_SUFFIX}-$(date +%Y%m%d-%H%M%S)"

  # Resolve {AREA} placeholder in title
  export PIPELINE_TITLE="${ORIG_PIPELINE_TITLE//\{AREA\}/$VM_SUFFIX}"

  echo "--- VM $IDX/$VM_COUNT: $VM_NAME ---"

  # 1. Prepare startup script (concatenate + common seds)
  bash "${CICD_ROOT}/builders/prepare_vm_startup.sh"

  # 2. Copy to per-VM path to avoid overwriting in multi-VM loops
  STARTUP_FILE="/tmp/startup-script-${VM_SUFFIX}.sh"
  cp /tmp/startup-script.sh "$STARTUP_FILE"

  # 3. Apply per-VM config as sed replacements
  while IFS= read -r LINE; do
    [[ -z "$LINE" || "$LINE" =~ ^# || "$LINE" != *"="* ]] && continue
    KEY="${LINE%%=*}"
    VALUE="${LINE#*=}"
    # Use '#' delimiter for values containing '|', otherwise '|'
    if [[ "$VALUE" == *"|"* ]]; then
      sed -i "s#__${KEY}__#${VALUE}#g" "$STARTUP_FILE"
    else
      sed -i "s|__${KEY}__|${VALUE}|g" "$STARTUP_FILE"
    fi
  done < "$CONFIG_FILE"

  # 4. Create VM (export_vm_defaults.sh must be sourced, not bashed)
  export STARTUP_SCRIPT="$STARTUP_FILE"
  source "${CICD_ROOT}/builders/export_vm_defaults.sh"
  bash "${CICD_ROOT}/builders/create_vm.sh"

  # Collect VM names
  ALL_VM_NAMES="${ALL_VM_NAMES:+${ALL_VM_NAMES} }${VM_NAME}"
  echo ""
done

# Save all VM names (overwrites per-VM writes from create_vm.sh)
echo "$ALL_VM_NAMES" > /workspace/vm_names.txt

echo "=========================================="
echo "All $VM_COUNT VM(s) created successfully"
echo "=========================================="
