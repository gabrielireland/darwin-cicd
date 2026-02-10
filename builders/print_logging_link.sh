#!/bin/bash
set -euo pipefail
# ========================================
# Print Cloud Logging Link
# ========================================
# Reads VM instance ID and zone from /workspace/ files
# and prints a clickable Cloud Logging link.
#
# Required env vars:
#   PROJECT_ID - GCP project ID
# ========================================

INSTANCE_ID=$(cat /workspace/vm_instance_id.txt 2>/dev/null || echo "")
VM_ZONE=$(cat /workspace/vm_zone.txt 2>/dev/null || echo "")

if [ -n "$INSTANCE_ID" ] && [ -n "$VM_ZONE" ]; then
  echo ""
  echo "========================================================"
  echo "      CLOUD LOGGING LINK"
  echo "========================================================"
  LOGS_QUERY="resource.type%3D%22gce_instance%22%20resource.labels.zone%3D%22${VM_ZONE}%22%20resource.labels.instance_id%3D%22${INSTANCE_ID}%22%20severity%3E%3DDEFAULT"
  echo "https://console.cloud.google.com/logs/query;query=${LOGS_QUERY};project=${PROJECT_ID}"
fi
