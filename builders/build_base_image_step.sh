#!/bin/bash
# ========================================
# Build Base Image (CloudBuild Step)
# ========================================
# Replaces the inline 'build-base-image' step in all pipeline YAMLs.
# Reads Dockerfile path and image name from defaults.yaml.
#
# Required env vars (from CloudBuild):
#   _UPDATE_BASE  - 'true' to rebuild, 'false' to skip
#   _REGION       - GCP region
#   PROJECT_ID    - GCP project ID
#   DEFAULTS_FILE - Path to project's defaults.yaml
# ========================================
set -euo pipefail

CICD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${CICD_ROOT}/config/load_defaults.sh"

export _UPDATE_BASE="${_UPDATE_BASE:-${CB_UPDATE_BASE}}"
export _REGION="${_REGION:-${CB_REGION}}"
export PROJECT_ID="${PROJECT_ID:?Missing PROJECT_ID}"
export DOCKERFILE_PATH="${CB_DOCKERFILE_BASE_PATH}"
export IMAGE_NAME="${CB_BASE_IMAGE_NAME}"

bash "${CICD_ROOT}/builders/build_base_image.sh"
