#!/bin/bash
# ========================================
# Build Code Layer (CloudBuild Step)
# ========================================
# Replaces the inline 'build-code-layer' step in all pipeline YAMLs.
# Only CODE_IMAGE_NAME varies per pipeline.
#
# Required env vars (from CloudBuild):
#   _REGION          - GCP region
#   PROJECT_ID       - GCP project ID
#   SHORT_SHA        - Git commit SHA (used as image tag)
#   CODE_IMAGE_NAME  - Pipeline-specific image name
#   DEFAULTS_FILE    - Path to project's defaults.yaml
#
# Optional:
#   _RUN_NAME_PREFIX - Defaults to CODE_IMAGE_NAME
# ========================================
set -euo pipefail

CICD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${CICD_ROOT}/config/load_defaults.sh"

export _REGION="${_REGION:-${CB_REGION}}"
export PROJECT_ID="${PROJECT_ID:?Missing PROJECT_ID}"
export SHORT_SHA="${SHORT_SHA:?Missing SHORT_SHA}"
export DOCKERFILE_PATH="${CB_DOCKERFILE_CODE_PATH}"
export BASE_IMAGE_NAME="${CB_BASE_IMAGE_NAME}"
export CODE_IMAGE_NAME="${CODE_IMAGE_NAME:?Missing CODE_IMAGE_NAME}"
export _RUN_NAME_PREFIX="${_RUN_NAME_PREFIX:-${CODE_IMAGE_NAME}}"

bash "${CICD_ROOT}/builders/build_code_image.sh"
