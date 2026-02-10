#!/bin/bash
# ========================================
# UNIFIED Base Image Builder
# ========================================
# Builds Docker base images for any pipeline (training, change detection, etc.)
#
# Required environment variables:
#   _REGION         - GCP region (e.g., europe-west1)
#   PROJECT_ID      - GCP project ID
#   _UPDATE_BASE    - Set to 'true' to rebuild base image
#   DOCKERFILE_PATH - Path to Dockerfile.base (e.g., docker/training/Dockerfile.base)
#   IMAGE_NAME      - Base image name (e.g., ml-training-base, change-detection-base)
#
# Optional:
#   BASE_TAG        - Image tag (default: latest)
#
set -euo pipefail

UPDATE_BASE=$(echo "${_UPDATE_BASE:-false}" | tr '[:upper:]' '[:lower:]')

if [[ "$UPDATE_BASE" != "true" ]]; then
  echo "⏭️  Skipping base image build (_UPDATE_BASE=${_UPDATE_BASE:-false})"
  echo "ℹ️  Set _UPDATE_BASE=true when requirements or Dockerfile.base change."
  exit 0
fi

# Required variables
REGION="${_REGION:?Missing _REGION}"
PROJECT="${PROJECT_ID:?Missing PROJECT_ID}"
DOCKERFILE_PATH="${DOCKERFILE_PATH:?Missing DOCKERFILE_PATH - set in Cloud Build YAML}"
IMAGE_NAME="${IMAGE_NAME:?Missing IMAGE_NAME - set in Cloud Build YAML}"

# Construct image URI
REPOSITORY="${PROJECT}-docker"
BASE_TAG="${BASE_TAG:-latest}"
BASE_IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}/${IMAGE_NAME}:${BASE_TAG}"

echo "=========================================="
echo "🔨 Building Base Image with Dependencies"
echo "=========================================="
echo "Image URI   : ${BASE_IMAGE_URI}"
echo "Dockerfile  : ${DOCKERFILE_PATH}"
echo "Context     : $(pwd)"

# Verify Dockerfile exists
if [[ ! -f "$DOCKERFILE_PATH" ]]; then
  echo "❌ ERROR: Dockerfile not found at ${DOCKERFILE_PATH}"
  exit 1
fi

# Build image
docker build \
  --platform=linux/amd64 \
  -t "${BASE_IMAGE_URI}" \
  -f "${DOCKERFILE_PATH}" \
  --progress=plain \
  .

echo "📤 Pushing base image to Artifact Registry..."
docker push "${BASE_IMAGE_URI}"

echo "✅ Base image built and pushed successfully"
echo "   ${BASE_IMAGE_URI}"
