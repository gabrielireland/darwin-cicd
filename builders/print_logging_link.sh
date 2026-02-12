#!/bin/bash
set -euo pipefail
# ========================================
# Print Cloud Logging Links (all VMs)
# ========================================
# Reads per-VM instance IDs and zones from /workspace/ files
# and prints a clickable Cloud Logging link for each VM.
#
# Required env vars:
#   PROJECT_ID - GCP project ID
# ========================================

VM_COUNT=$(cat /workspace/vm_count.txt 2>/dev/null || echo "0")

if [ "$VM_COUNT" -gt 0 ]; then
  echo ""
  echo "========================================================"
  echo "      CLOUD LOGGING LINKS"
  echo "========================================================"

  for IDX in $(seq 1 "$VM_COUNT"); do
    INSTANCE_ID=$(cat "/workspace/vm_instance_id_${IDX}.txt" 2>/dev/null || echo "")
    VM_ZONE=$(cat "/workspace/vm_zone_${IDX}.txt" 2>/dev/null || echo "")
    VM_NAME=$(cat "/workspace/vm_name_${IDX}.txt" 2>/dev/null || echo "VM ${IDX}")

    if [ -n "$INSTANCE_ID" ] && [ -n "$VM_ZONE" ]; then
      LOGS_QUERY="resource.type%3D%22gce_instance%22%20resource.labels.zone%3D%22${VM_ZONE}%22%20resource.labels.instance_id%3D%22${INSTANCE_ID}%22%20severity%3E%3DDEFAULT"
      echo ""
      echo "  ${VM_NAME}:"
      echo "  https://console.cloud.google.com/logs/query;query=${LOGS_QUERY};project=${PROJECT_ID}"
    fi
  done

  echo ""
fi
