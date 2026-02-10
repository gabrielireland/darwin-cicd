#!/bin/bash
# Shared VM creation/reuse helper for training pipelines.
set -euo pipefail

RUN_TRAINING=$(echo "${_RUN_TRAINING:-true}" | tr '[:upper:]' '[:lower:]')
if [[ "$RUN_TRAINING" != "true" ]]; then
  echo "⏭️  Skipping training (_RUN_TRAINING=$RUN_TRAINING)"
  exit 0
fi

STARTUP_TEMPLATE="${STARTUP_SCRIPT:?STARTUP_SCRIPT not set}"
if [[ ! -f "$STARTUP_TEMPLATE" ]]; then
  echo "❌ STARTUP_SCRIPT not found: $STARTUP_TEMPLATE"
  exit 1
fi

TRAINING_ZONES="${TRAINING_ZONES:-europe-west1-d,europe-west1-c,europe-west1-b}"
IFS=',' read -ra ZONES <<< "$TRAINING_ZONES"
if [[ ${#ZONES[@]} -eq 0 ]]; then
  echo "❌ No zones configured in TRAINING_ZONES"
  exit 1
fi

VM_NAME="${VM_NAME:-ml-training-gpu-$(date +%Y%m%d-%H%M%S)}"
# Extract VM prefix (everything before the timestamp)
VM_PREFIX=$(echo "$VM_NAME" | sed -E 's/-[0-9]{8}-[0-9]{6}$//')

MACHINE_TYPE="${_MACHINE_TYPE:?Missing _MACHINE_TYPE}"
GPU_TYPE="${_GPU_TYPE:-}"  # Can be empty for CPU-only VMs
GPU_COUNT="${_GPU_COUNT:-0}"  # Default to 0 for CPU-only VMs
BOOT_DISK_SIZE="${_BOOT_DISK_SIZE:?Missing _BOOT_DISK_SIZE}"
VM_SERVICE_ACCOUNT="${_VM_SERVICE_ACCOUNT:?Missing _VM_SERVICE_ACCOUNT}"
USE_SPOT=$(echo "${_USE_SPOT:-false}" | tr '[:upper:]' '[:lower:]')
MAX_RUN_DURATION="${MAX_RUN_DURATION:-5h}"
INSTANCE_LABELS="${INSTANCE_LABELS:-type=ml-training,build=${SHORT_SHA:-unknown},model=unknown}"
INSTANCE_METADATA="${INSTANCE_METADATA:-google-logging-enabled=true,google-monitoring-enabled=true,install-nvidia-driver=True,startup-script-running=TRUE}"
GPU_IMAGE_FAMILY="${GPU_IMAGE_FAMILY:-pytorch-2-7-cu128-ubuntu-2204-nvidia-570}"
GPU_IMAGE_PROJECT="${GPU_IMAGE_PROJECT:-deeplearning-platform-release}"
BOOT_DISK_TYPE="${BOOT_DISK_TYPE:-pd-standard}"
VM_ZONE_FILE="${VM_ZONE_FILE:-/workspace/vm_zone.txt}"

# ========================================
# Check for existing VMs with same prefix (cleanup only)
# ========================================
echo ""
echo "=========================================="
echo "🔍 Checking for existing VMs with prefix: ${VM_PREFIX}"
echo "=========================================="

# Search across all configured zones for old VMs to clean up
for RAW_ZONE in "${ZONES[@]}"; do
  ZONE="$(echo "$RAW_ZONE" | xargs)"
  [[ -z "$ZONE" ]] && continue

  # List VMs matching the prefix in this zone
  MATCHING_VMS=$(gcloud compute instances list \
    --zones="$ZONE" \
    --filter="name:${VM_PREFIX}*" \
    --format="value(name,status)" 2>/dev/null || echo "")

  if [[ -n "$MATCHING_VMS" ]]; then
    while IFS= read -r VM_LINE; do
      OLD_VM_NAME=$(echo "$VM_LINE" | awk '{print $1}')
      OLD_VM_STATUS=$(echo "$VM_LINE" | awk '{print $2}')

      [[ -z "$OLD_VM_NAME" ]] && continue

      echo "Found: ${OLD_VM_NAME} (status: ${OLD_VM_STATUS}) in zone ${ZONE}"

      case "$OLD_VM_STATUS" in
        RUNNING)
          echo "  ⏭️  Skipping - VM is actively running (parallel execution allowed)"
          ;;
        SUSPENDED|TERMINATED|STOPPING|SUSPENDING|STAGING)
          echo "  🗑️  Cleaning up stopped/terminated VM..."
          gcloud compute instances delete "$OLD_VM_NAME" --zone="$ZONE" --quiet || true
          ;;
        *)
          echo "  ⚠️  Unknown status, skipping..."
          ;;
      esac
    done <<< "$MATCHING_VMS"
  fi
done

echo ""
echo "✅ Cleanup complete. Creating new VM with fresh name: ${VM_NAME}"

# ========================================
# Create new VM if no existing VM found/usable
# ========================================
echo ""
echo "=========================================="
echo "🆕 Creating New VM: ${VM_NAME}"
echo "=========================================="

VM_CREATED=false
ACTUAL_ZONE=""

for RAW_ZONE in "${ZONES[@]}"; do
  ZONE="$(echo "$RAW_ZONE" | xargs)"
  [[ -z "$ZONE" ]] && continue

  echo ""
  echo "Trying zone: $ZONE..."

  # Use the already-processed startup script (has all sed replacements from CloudBuild)
  # Just need to replace the zone placeholder
  sed "s|__VM_ZONE__|$ZONE|g" "$STARTUP_TEMPLATE" > "/tmp/startup-script-${ZONE}.sh"
  ZONE_STARTUP="/tmp/startup-script-${ZONE}.sh"

  CREATE_CMD=(gcloud compute instances create "$VM_NAME"
    --zone="$ZONE"
    --machine-type="$MACHINE_TYPE"
    --boot-disk-size="$BOOT_DISK_SIZE"
    --boot-disk-type="$BOOT_DISK_TYPE"
    --max-run-duration="$MAX_RUN_DURATION"
    --instance-termination-action=DELETE
    --service-account="$VM_SERVICE_ACCOUNT"
    --scopes=cloud-platform
    --metadata-from-file="startup-script=$ZONE_STARTUP"
    --metadata="$INSTANCE_METADATA"
    --labels="$INSTANCE_LABELS"
  )

  # Add GPU-specific flags only if GPU is requested
  if [[ -n "$GPU_TYPE" && "$GPU_COUNT" -gt 0 ]]; then
    CREATE_CMD+=(
      --accelerator="type=$GPU_TYPE,count=$GPU_COUNT"
      --image-family="$GPU_IMAGE_FAMILY"
      --image-project="$GPU_IMAGE_PROJECT"
      --maintenance-policy=TERMINATE
    )
    echo "🎮 GPU Configuration: $GPU_COUNT x $GPU_TYPE"
  else
    # CPU-only: use standard Ubuntu image
    CREATE_CMD+=(
      --image-family="${CPU_IMAGE_FAMILY:-ubuntu-2204-lts}"
      --image-project="${CPU_IMAGE_PROJECT:-ubuntu-os-cloud}"
    )
    echo "💻 CPU-only VM (no GPU)"
  fi

  if [[ "$USE_SPOT" == "true" ]]; then
    CREATE_CMD+=("--provisioning-model=SPOT" "--instance-termination-action=DELETE")
    echo "💰 Using Spot instances (70% cheaper, better availability)"
  fi

  if "${CREATE_CMD[@]}" 2>&1; then
    VM_CREATED=true
    ACTUAL_ZONE="$ZONE"
    break
  else
    echo "❌ Zone $ZONE unavailable, trying next..."
  fi
done

if [[ "$VM_CREATED" != "true" ]]; then
  echo ""
  echo "=========================================="
  if [[ -n "$GPU_TYPE" && "$GPU_COUNT" -gt 0 ]]; then
    echo "❌ FAILED: No GPU availability in configured zones"
  else
    echo "❌ FAILED: Could not create VM in any configured zone"
  fi
  echo "=========================================="
  exit 1
fi

echo "$ACTUAL_ZONE" > "$VM_ZONE_FILE"
echo "$VM_NAME" > /workspace/vm_names.txt

# Get the instance ID for Cloud Logging
INSTANCE_ID=$(gcloud compute instances describe "$VM_NAME" --zone="$ACTUAL_ZONE" --format='get(id)' 2>/dev/null || echo "")
echo "$INSTANCE_ID" > /workspace/vm_instance_id.txt

echo ""
if [[ -n "$GPU_TYPE" && "$GPU_COUNT" -gt 0 ]]; then
  echo "✅ GPU VM created successfully in zone: $ACTUAL_ZONE"
else
  echo "✅ CPU VM created successfully in zone: $ACTUAL_ZONE"
fi
echo "🚀 Processing will start automatically"
echo "📊 Monitor progress: gcloud compute instances get-serial-port-output $VM_NAME --zone=$ACTUAL_ZONE"

echo ""
echo "=========================================="
echo "📋 CLOUD LOGGING LINK"
echo "=========================================="
PROJECT_ID_FOR_URL="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -n "$INSTANCE_ID" ]]; then
  LOGS_QUERY="resource.type%3D%22gce_instance%22%20resource.labels.zone%3D%22${ACTUAL_ZONE}%22%20resource.labels.instance_id%3D%22${INSTANCE_ID}%22%20severity%3E%3DDEFAULT"
else
  LOGS_QUERY="resource.type%3D%22gce_instance%22%20%22${VM_NAME}%22%20severity%3E%3DDEFAULT"
fi
echo "https://console.cloud.google.com/logs/query;query=${LOGS_QUERY};project=${PROJECT_ID_FOR_URL}"
echo "=========================================="
