# Creating a New CloudBuild VM Pipeline

This guide walks through creating a complete pipeline: CloudBuild YAML + VM startup script.

## Architecture

Every pipeline follows the same 6-step pattern:

```
init-submodules → validate-inputs → build-base-image → build-code-layer → create-vm → summary-report
```

The VM runs asynchronously — CloudBuild creates it and exits. The VM processes data, uploads results to GCS, and self-deletes.

## Step 1: Create the VM Startup Script

Create `cloudbuild-builds/vm/my_pipeline.sh`:

```bash
#!/bin/bash
# ========================================
# My Pipeline - VM Startup Script
# ========================================
# This file is concatenated AFTER preflight_check.sh and startup_common.sh
# by prepare_vm_startup.sh. All common functions are already available.
#
# Available variables (replaced by sed before VM creation):
#   Common (handled by prepare_vm_startup.sh):
#     __REGION__, __IMAGE_URI__, __BUCKET__, __VM_NAME__, __VM_ZONE__,
#     __BUILD_ID__, __GIT_COMMIT__, __CLOUDBUILD_YAML__, __PIPELINE_TITLE__
#
#   Pipeline-specific (you add sed replacements in your YAML):
#     __MY_PARAM__, __MY_OTHER_PARAM__, etc.
# ========================================

# ---- Configuration (sed-replaced at build time) ----
BUCKET="__BUCKET__"
REGION="__REGION__"
IMAGE_URI="__IMAGE_URI__"
VM_NAME="__VM_NAME__"
VM_ZONE="__VM_ZONE__"
BUILD_ID="__BUILD_ID__"
GIT_COMMIT="__GIT_COMMIT__"

# Pipeline-specific placeholders
MY_PARAM="__MY_PARAM__"
MY_OTHER_PARAM="__MY_OTHER_PARAM__"

# ---- Paths ----
LOCAL_OUTPUT_DIR="/tmp/pipeline_output"
OUTPUT_GCS="gs://${BUCKET}/Laboratory/MyOutput/${MY_PARAM}"
mkdir -p "$LOCAL_OUTPUT_DIR"

# ---- Docker Run ----
# startup_common.sh already authenticated Docker and pulled the image.
# Just run your container:
docker run --rm \
  -e PYTHONUNBUFFERED=1 \
  -v "$LOCAL_OUTPUT_DIR":/workspace_output \
  "$IMAGE_URI" \
  python3 -m my_module.run \
    --param "$MY_PARAM" \
    --other "$MY_OTHER_PARAM" \
    --output /workspace_output

# ---- Upload Results ----
echo "Uploading results to GCS..."
gsutil -m rsync -r "$LOCAL_OUTPUT_DIR/" "$OUTPUT_GCS/"
echo "Upload complete: $OUTPUT_GCS"

# ---- Self-Cleanup ----
# The VM has --instance-termination-action=DELETE and --max-run-duration set,
# but explicit shutdown is good practice:
echo "Pipeline complete. Shutting down VM..."
sudo shutdown -h now
```

## Step 2: Create the CloudBuild YAML

Create `my-pipeline.yaml` (or any name you want):

```yaml
# ========================================
# Cloud Build Configuration - My Pipeline (VM-based)
# ========================================
# Description of what this pipeline does.
#
# Usage:
#   gcloud builds submit --config=my-pipeline.yaml
# ========================================

# ========================================
# PARAMETERS
# ========================================
substitutions:
  # ---- Pipeline-specific ----
  _MY_PARAM: 'default_value'
  _MY_OTHER_PARAM: 'default_value'

  # ---- Shared (from cloudbuild-builds/config/defaults.yaml) ----
  _REGION: 'europe-west1'
  _BUCKET: 'my-gcs-bucket'
  _MACHINE_TYPE: 'n2-highmem-8'
  _BOOT_DISK_SIZE: '200GB'
  _USE_SPOT: 'true'
  _MAX_RUN_DURATION: '6h'
  _SERVICE_ACCOUNT: 'projects/my-project/serviceAccounts/sa@my-project.iam.gserviceaccount.com'
  _VM_SERVICE_ACCOUNT: 'sa@my-project.iam.gserviceaccount.com'
  _UPDATE_BASE: 'false'

# ========================================
# PIPELINE STEPS
# ========================================
steps:
  # ========================================
  # Step 0: Init Submodules
  # ========================================
  - name: 'gcr.io/cloud-builders/git'
    id: 'init-submodules'
    args: ['submodule', 'update', '--init', '--recursive']

  # ========================================
  # Step 1: Validate Inputs
  # ========================================
  - name: 'gcr.io/cloud-builders/gcloud'
    id: 'validate-inputs'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        set -euo pipefail

        echo "==========================================="
        echo "My Pipeline - Input Validation"
        echo "==========================================="
        echo "Param:       ${_MY_PARAM}"
        echo "Other Param: ${_MY_OTHER_PARAM}"

        # Validate inputs exist in GCS (example)
        # INPUT_GCS="gs://${_BUCKET}/path/to/input"
        # if ! gsutil -q stat "$${INPUT_GCS}"; then
        #   echo "ERROR: Input not found: $${INPUT_GCS}"
        #   exit 1
        # fi

        # Save workspace state for later steps
        echo "my_value" > /workspace/my_state.txt

        echo "All inputs validated"
    waitFor: ['init-submodules']

  # ========================================
  # Step 2: Build Base Image
  # ========================================
  - name: 'gcr.io/cloud-builders/docker'
    id: 'build-base-image'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        set -euo pipefail
        export DEFAULTS_FILE="cloudbuild-builds/config/defaults.yaml"
        export _UPDATE_BASE="${_UPDATE_BASE}"
        export _REGION="${_REGION}"
        export PROJECT_ID="${PROJECT_ID}"
        bash cicd/builders/build_base_image_step.sh
    waitFor: ['init-submodules']

  # ========================================
  # Step 3: Build Code Layer
  # ========================================
  - name: 'gcr.io/cloud-builders/docker'
    id: 'build-code-layer'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        set -euo pipefail
        export DEFAULTS_FILE="cloudbuild-builds/config/defaults.yaml"
        export _REGION="${_REGION}"
        export PROJECT_ID="${PROJECT_ID}"
        export SHORT_SHA="${SHORT_SHA}"
        export CODE_IMAGE_NAME="my-pipeline"      # <-- Your image name
        bash cicd/builders/build_code_image_step.sh
    waitFor: ['build-base-image']

  # ========================================
  # Step 4: Create VM
  # ========================================
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    id: 'create-vm'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        set -euo pipefail
        export DEFAULTS_FILE="cloudbuild-builds/config/defaults.yaml"

        # ---- VM identity ----
        export VM_NAME="my-pipeline-$(date +%Y%m%d-%H%M%S)"
        export CODE_IMAGE_NAME="my-pipeline"
        export CLOUDBUILD_YAML="my-pipeline.yaml"
        export PIPELINE_TITLE="My Pipeline"
        export VM_SCRIPT_NAME="my_pipeline.sh"     # <-- Matches filename in cloudbuild-builds/vm/

        # ---- CloudBuild vars ----
        export PROJECT_ID="${PROJECT_ID}"
        export SHORT_SHA="${SHORT_SHA}"
        export BUILD_ID="${BUILD_ID}"
        export _REGION="${_REGION}"
        export _BUCKET="${_BUCKET}"

        # ---- 1. Prepare startup script (common sed replacements) ----
        bash cicd/builders/prepare_vm_startup.sh

        # ---- 2. Pipeline-specific sed replacements ----
        sed -i "s|__MY_PARAM__|${_MY_PARAM}|g" /tmp/startup-script.sh
        sed -i "s|__MY_OTHER_PARAM__|${_MY_OTHER_PARAM}|g" /tmp/startup-script.sh

        # ---- 3. Export VM defaults ----
        export _MACHINE_TYPE="${_MACHINE_TYPE}"
        export _BOOT_DISK_SIZE="${_BOOT_DISK_SIZE}"
        export _VM_SERVICE_ACCOUNT="${_VM_SERVICE_ACCOUNT}"
        export _USE_SPOT="${_USE_SPOT}"
        source cicd/builders/export_vm_defaults.sh

        # ---- 4. Create VM ----
        export INSTANCE_LABELS="type=my-pipeline,build=${SHORT_SHA}"
        export MAX_RUN_DURATION="${_MAX_RUN_DURATION}"
        bash cicd/builders/create_vm.sh
    waitFor: ['build-code-layer', 'validate-inputs']

  # ========================================
  # Step 5: Summary Report
  # ========================================
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    id: 'summary-report'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        echo ""
        echo "========================================================"
        echo "      MY PIPELINE - SUMMARY"
        echo "========================================================"
        echo ""
        echo "Build ID:    ${BUILD_ID}"
        echo "Commit SHA:  ${SHORT_SHA}"
        echo "Param:       ${_MY_PARAM}"
        echo ""
        echo "Output:"
        echo "   gs://${_BUCKET}/Laboratory/MyOutput/${_MY_PARAM}/"
        echo ""
        echo "VM is processing asynchronously and will auto-shutdown when done"

        # Cloud Logging link
        export DEFAULTS_FILE="cloudbuild-builds/config/defaults.yaml"
        export PROJECT_ID="${PROJECT_ID}"
        bash cicd/builders/print_logging_link.sh

        echo "========================================================"
    waitFor: ['create-vm']

# ========================================
# Build Options
# ========================================
options:
  logging: CLOUD_LOGGING_ONLY
  machineType: 'E2_HIGHCPU_8'

serviceAccount: '${_SERVICE_ACCOUNT}'

timeout: '7200s'
```

## Step 3: Create Dockerfiles

Create `cloudbuild-builds/docker/Dockerfile.base` (dependencies, rebuilt rarely):

```dockerfile
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy pandas gcsfs
```

Create `cloudbuild-builds/docker/Dockerfile` (code layer, rebuilt every commit):

```dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY src/ /app/src/
WORKDIR /app
```

## Step 4: Run it

Edit the substitution values in your YAML, then:

```bash
gcloud builds submit --config=my-pipeline.yaml
```

## Checklist

Before running, verify:

- [ ] `cloudbuild-builds/vm/my_pipeline.sh` exists with your pipeline logic
- [ ] `cloudbuild-builds/config/defaults.yaml` has correct values for your project
- [ ] `cloudbuild-builds/docker/Dockerfile.base` and `Dockerfile` exist
- [ ] YAML `substitutions` section has your pipeline parameters
- [ ] YAML `CODE_IMAGE_NAME` matches across `build-code-layer` and `create-vm` steps
- [ ] YAML `VM_SCRIPT_NAME` matches your VM script filename
- [ ] All `__PLACEHOLDER__` values in your VM script have matching `sed` replacements in the YAML
- [ ] Every step that calls `cicd/` scripts exports `DEFAULTS_FILE`
- [ ] `export_vm_defaults.sh` is called with `source`, not `bash`
- [ ] All bash steps start with `set -euo pipefail`

## Common Customizations

### Adding GPU support

In the create-vm step, add before `source cicd/builders/export_vm_defaults.sh`:

```bash
export _GPU_TYPE="nvidia-tesla-t4"
export _GPU_COUNT="1"
```

### Reading workspace state from validation step

```bash
MY_STATE=$$(cat /workspace/my_state.txt)
sed -i "s|__MY_STATE__|$$MY_STATE|g" /tmp/startup-script.sh
```

Note: `$$` for bash vars in CloudBuild YAML, single `$` for CloudBuild substitutions.

### Values containing pipe `|` characters

Use `#` as sed delimiter:

```bash
sed -i "s#__PIPE_VALUE__#$${VALUE_WITH_PIPES}#g" /tmp/startup-script.sh
```

### Skipping base image rebuild

Set `_UPDATE_BASE: 'false'` (default). The base image is cached in Artifact Registry and only rebuilt when `_UPDATE_BASE: 'true'`.
