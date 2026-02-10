#!/bin/bash
# ========================================
# UNIFIED Code Layer Builder
# ========================================
# Builds thin code layer on top of base images for any pipeline
#
# Required environment variables:
#   _REGION         - GCP region (e.g., europe-west1)
#   PROJECT_ID      - GCP project ID
#   SHORT_SHA       - Git commit SHA for tagging
#   DOCKERFILE_PATH - Path to Dockerfile (e.g., docker/training/Dockerfile)
#   BASE_IMAGE_NAME - Base image name (e.g., ml-training-base, change-detection-base)
#   CODE_IMAGE_NAME - Final image name (e.g., ml-training, change-detection)
#
# Optional:
#   _RUN_NAME_PREFIX - Pipeline name for tagging (default: code image name)
#
set -euo pipefail

REGION="${_REGION:?Missing _REGION}"
PROJECT="${PROJECT_ID:?Missing PROJECT_ID}"
REPOSITORY="${PROJECT}-docker"
SHA_TAG="${SHORT_SHA:?Missing SHORT_SHA}"
DOCKERFILE_PATH="${DOCKERFILE_PATH:?Missing DOCKERFILE_PATH - set in Cloud Build YAML}"
BASE_IMAGE_NAME="${BASE_IMAGE_NAME:?Missing BASE_IMAGE_NAME - set in Cloud Build YAML}"
CODE_IMAGE_NAME="${CODE_IMAGE_NAME:?Missing CODE_IMAGE_NAME - set in Cloud Build YAML}"

# Optional pipeline tag (defaults to code image name)
PIPELINE_TAG="${_RUN_NAME_PREFIX:-${CODE_IMAGE_NAME}}"
TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)

BASE_IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}/${BASE_IMAGE_NAME}:latest"
CODE_IMAGE_PREFIX="${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}/${CODE_IMAGE_NAME}"

echo "=========================================="
echo "⚡ Building Code Layer (Fast!)"
echo "=========================================="
echo "Base image  : ${BASE_IMAGE}"
echo "Code image  : ${CODE_IMAGE_NAME}"
echo "Dockerfile  : ${DOCKERFILE_PATH}"
echo "Commit SHA  : ${SHA_TAG}"
echo "Pipeline    : ${PIPELINE_TAG}"
echo "Timestamp   : ${TIMESTAMP}"

# Verify Dockerfile exists
if [[ ! -f "$DOCKERFILE_PATH" ]]; then
  echo "❌ ERROR: Dockerfile not found at ${DOCKERFILE_PATH}"
  exit 1
fi

echo "📥 Pulling base image for cache..."
if ! docker pull "${BASE_IMAGE}" >/dev/null 2>&1; then
  cat <<EOF

❌ Base image not found: ${BASE_IMAGE}

Build the base image first by running your pipeline with:
  --substitutions=_UPDATE_BASE=true

This rebuilds the base image with all dependencies.
EOF
  exit 1
fi

echo "🔨 Building code layer..."
docker build \
  --platform=linux/amd64 \
  --build-arg BASE_IMAGE="${BASE_IMAGE}" \
  -t "${CODE_IMAGE_PREFIX}:${SHA_TAG}" \
  -t "${CODE_IMAGE_PREFIX}:${PIPELINE_TAG}-${SHA_TAG}" \
  -t "${CODE_IMAGE_PREFIX}:${PIPELINE_TAG}-${TIMESTAMP}" \
  -t "${CODE_IMAGE_PREFIX}:latest" \
  -f "${DOCKERFILE_PATH}" \
  .

echo "📤 Pushing code layer with all tags..."
docker push --all-tags "${CODE_IMAGE_PREFIX}"

echo "✅ Code layer built and pushed successfully"
echo "   Primary tag: ${CODE_IMAGE_PREFIX}:${SHA_TAG}"
