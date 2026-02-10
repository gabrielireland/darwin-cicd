# ========================================
# Code Layer Dockerfile
# ========================================
#
# Fast-rebuilding layer on top of base dependencies.
# Contains ONLY application code — rebuilt every commit.
#
# The BASE_IMAGE arg is set automatically by build_code_image_step.sh
# from your defaults.yaml base_image_name value.
#
# Build:
#   docker build --build-arg BASE_IMAGE=my-base:latest \
#     -t my-code:latest -f cloudbuild-builds/docker/my_project/Dockerfile .
#

ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# Switch to root to copy files
USER root

# ========================================
# Copy Application Code
# ========================================
COPY --chown=1000:1000 . /app/

# Switch back to non-root user
USER 1000

WORKDIR /app

# ========================================
# Default Entrypoint
# ========================================
# Override per pipeline via: docker run <image> python -m my_module.run
ENTRYPOINT ["python"]
