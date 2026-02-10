# darwin-cicd

Reusable CI/CD scripts for Google CloudBuild VM-based pipelines.

Handles Docker image builds, VM creation with zone fallback, startup script assembly, and Cloud Logging integration. Designed to be consumed as a **git submodule**.

## Guides

- **[Setup Guide](docs/SETUP.md)** — Add this module to your project
- **[Pipeline Guide](docs/PIPELINE_GUIDE.md)** — Create a new CloudBuild VM pipeline from scratch (full YAML + VM script template)

## Quick Start

### 1. Add the submodule

```bash
git submodule add https://github.com/gabrielireland/darwin-cicd.git cicd
```

### 2. Create your `defaults.yaml`

Create a config file in your project (e.g. `cloudbuild-builds/config/defaults.yaml`):

```yaml
# Required
region: 'europe-west1'
bucket: 'my-gcs-bucket'
service_account: 'projects/my-project/serviceAccounts/sa-ci-cd@my-project.iam.gserviceaccount.com'
vm_service_account: 'sa-ci-cd@my-project.iam.gserviceaccount.com'

# Docker
dockerfile_base_path: 'docker/Dockerfile.base'
dockerfile_code_path: 'docker/Dockerfile'
base_image_name: 'my-base-image'

# VM
vm_zones: 'europe-west1-d,europe-west1-c,europe-west1-b'
boot_disk_size: '200GB'
update_base: 'false'
```

### 3. Add to your CloudBuild YAML

```yaml
steps:
  # REQUIRED: Clone submodule (CloudBuild does NOT auto-clone submodules)
  - name: 'gcr.io/cloud-builders/git'
    id: 'init-submodules'
    args: ['submodule', 'update', '--init', '--recursive']

  # Build Docker base image
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

  # Build Docker code layer
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
        export CODE_IMAGE_NAME="my-pipeline"
        bash cicd/builders/build_code_image_step.sh
    waitFor: ['build-base-image']

  # Create VM
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    id: 'create-vm'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        set -euo pipefail
        export DEFAULTS_FILE="cloudbuild-builds/config/defaults.yaml"

        # Prepare startup script (concatenates utils + your VM script)
        export VM_NAME="my-pipeline-$(date +%Y%m%d-%H%M%S)"
        export CODE_IMAGE_NAME="my-pipeline"
        export CLOUDBUILD_YAML="my-pipeline.yaml"
        export PIPELINE_TITLE="My Pipeline"
        export VM_SCRIPT_NAME="my_pipeline.sh"
        export PROJECT_ID="${PROJECT_ID}"
        export SHORT_SHA="${SHORT_SHA}"
        export BUILD_ID="${BUILD_ID}"
        export _REGION="${_REGION}"
        export _BUCKET="${_BUCKET}"
        bash cicd/builders/prepare_vm_startup.sh

        # Pipeline-specific sed replacements (after common ones are done)
        sed -i "s|__MY_PARAM__|${_MY_PARAM}|g" /tmp/startup-script.sh

        # Export VM defaults and create
        export _MACHINE_TYPE="${_MACHINE_TYPE}"
        export _BOOT_DISK_SIZE="${_BOOT_DISK_SIZE}"
        export _VM_SERVICE_ACCOUNT="${_VM_SERVICE_ACCOUNT}"
        export _USE_SPOT="${_USE_SPOT}"
        source cicd/builders/export_vm_defaults.sh
        export INSTANCE_LABELS="type=my-pipeline,build=${SHORT_SHA}"
        export MAX_RUN_DURATION="${_MAX_RUN_DURATION}"
        bash cicd/builders/create_vm.sh
    waitFor: ['build-code-layer']

  # Summary with logging link
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    id: 'summary-report'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        export DEFAULTS_FILE="cloudbuild-builds/config/defaults.yaml"
        export PROJECT_ID="${PROJECT_ID}"
        echo "Pipeline submitted. VM is processing asynchronously."
        bash cicd/builders/print_logging_link.sh
    waitFor: ['create-vm']
```

---

## Architecture

### How scripts find each other

Every script resolves its own location using `BASH_SOURCE[0]`:

```
CICD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${CICD_ROOT}/config/load_defaults.sh"
```

This makes the submodule **location-independent** — it works regardless of where it's mounted.

### Configuration flow

```
Your project                          cicd/ submodule
─────────────                         ────────────────
defaults.yaml ──DEFAULTS_FILE──> load_defaults.sh ──> CB_REGION, CB_BUCKET, ...
                                                            │
CloudBuild YAML ──_REGION──> builder scripts use: ${_REGION:-${CB_REGION}}
                             (CloudBuild substitution wins, then defaults)
```

The `DEFAULTS_FILE` environment variable bridges your project's config to the submodule. **Every step that calls `cicd/` scripts must export it.**

### VM startup script assembly

`prepare_vm_startup.sh` concatenates three files into `/tmp/startup-script.sh`:

```
cicd/utils/preflight_check.sh     (file validation functions)
  + cicd/utils/startup_common.sh  (Docker pull, logging setup)
  + your_vm_script.sh             (pipeline-specific logic)
  = /tmp/startup-script.sh        (complete startup script)
```

Common `__PLACEHOLDER__` values are replaced automatically. Pipeline-specific placeholders need manual `sed` after calling `prepare_vm_startup.sh`.

The `VM_SCRIPTS_DIR` env var controls where your pipeline VM scripts live (default: `cloudbuild-builds/vm`).

---

## Scripts Reference

### Config

| Script | Purpose |
|--------|---------|
| `config/load_defaults.sh` | Parses `defaults.yaml` into `CB_*` env vars. Pure bash, no dependencies. |

### Builders

| Script | Call with | Purpose | Key env vars |
|--------|-----------|---------|-------------|
| `build_base_image_step.sh` | `bash` | Docker base image build | `DEFAULTS_FILE`, `_UPDATE_BASE`, `_REGION`, `PROJECT_ID` |
| `build_base_image.sh` | (internal) | Standalone base image builder | Called by step wrapper |
| `build_code_image_step.sh` | `bash` | Docker code layer build | `DEFAULTS_FILE`, `_REGION`, `PROJECT_ID`, `SHORT_SHA`, `CODE_IMAGE_NAME` |
| `build_code_image.sh` | (internal) | Standalone code image builder | Called by step wrapper |
| `prepare_vm_startup.sh` | `bash` | Assemble startup script + common sed | `DEFAULTS_FILE`, `VM_SCRIPT_NAME`, `VM_NAME`, `CODE_IMAGE_NAME`, `CLOUDBUILD_YAML`, `PIPELINE_TITLE`, `PROJECT_ID`, `SHORT_SHA`, `BUILD_ID` |
| `export_vm_defaults.sh` | **`source`** | Export VM config for create_vm.sh | `DEFAULTS_FILE`, `VM_NAME`, `_MACHINE_TYPE` |
| `create_vm.sh` | `bash` | Create VM with zone fallback + logging link | Uses exports from `export_vm_defaults.sh` |
| `print_logging_link.sh` | `bash` | Print Cloud Logging URL from workspace files | `PROJECT_ID` |

### Utils (concatenated, not called directly)

| Script | Purpose |
|--------|---------|
| `utils/preflight_check.sh` | GCS file validation functions for VM startup |
| `utils/startup_common.sh` | Docker auth, image pull, logging setup for VM startup |

---

## defaults.yaml Reference

All keys are optional — scripts use sensible defaults or fail with clear error messages.

| Key | Used by | Example |
|-----|---------|---------|
| `region` | All builders | `'europe-west1'` |
| `bucket` | `prepare_vm_startup.sh` | `'my-gcs-bucket'` |
| `service_account` | YAML `serviceAccount:` | `'projects/.../serviceAccounts/...'` |
| `vm_service_account` | `export_vm_defaults.sh` | `'sa-ci-cd@project.iam.gserviceaccount.com'` |
| `boot_disk_size` | `export_vm_defaults.sh` | `'200GB'` |
| `update_base` | `build_base_image_step.sh` | `'false'` |
| `dockerfile_base_path` | `build_base_image_step.sh` | `'docker/Dockerfile.base'` |
| `dockerfile_code_path` | `build_code_image_step.sh` | `'docker/Dockerfile'` |
| `base_image_name` | Both image builders | `'my-base-image'` |
| `vm_zones` | `export_vm_defaults.sh` | `'europe-west1-d,europe-west1-c'` |
| `source_bucket` | Project-specific scripts | `'my-source-bucket'` |
| `source_prefix` | Project-specific scripts | `'tiles/guest/raster'` |

Keys are parsed as `CB_` prefixed uppercase env vars: `region` becomes `CB_REGION`, `vm_zones` becomes `CB_VM_ZONES`.

---

## Common Placeholders

`prepare_vm_startup.sh` replaces these automatically in your VM startup scripts:

| Placeholder | Replaced with |
|-------------|---------------|
| `__REGION__` | GCP region |
| `__IMAGE_URI__` | Full Docker image URI with tag |
| `__BUCKET__` | GCS bucket name |
| `__OUTPUT_BUCKET__` | Same as `__BUCKET__` (backward compat) |
| `__VM_NAME__` | VM instance name |
| `__VM_ZONE__` | Actual zone (replaced by `create_vm.sh` during zone fallback) |
| `__BUILD_ID__` | CloudBuild build ID |
| `__GIT_COMMIT__` | Git commit SHA |
| `__CLOUDBUILD_YAML__` | Source YAML filename |
| `__PIPELINE_TITLE__` | Human-readable pipeline name |

Pipeline-specific placeholders (e.g. `__MODEL_ID__`, `__AREA__`) must be replaced with `sed` in your YAML after calling `prepare_vm_startup.sh`.

---

## VM Logging

Both `create_vm.sh` and `print_logging_link.sh` generate Cloud Logging URLs:

- **`create_vm.sh`**: Prints the logging link immediately after VM creation. Saves instance ID and zone to `/workspace/vm_instance_id.txt` and `/workspace/vm_zone.txt`.
- **`print_logging_link.sh`**: Reads those workspace files and prints the link again. Use this in summary steps.

The link filters directly to the specific VM instance in Cloud Logging console.

---

## Best Practices

### Shell strict mode

All scripts use `set -euo pipefail`. Your pipeline scripts should too.

```bash
#!/bin/bash
set -euo pipefail
```

### `source` vs `bash`

`export_vm_defaults.sh` **must** be called with `source` (not `bash`) because it exports environment variables that `create_vm.sh` needs. All other scripts use `bash`.

```bash
# CORRECT
source cicd/builders/export_vm_defaults.sh
bash cicd/builders/create_vm.sh

# WRONG - create_vm.sh won't see the exports
bash cicd/builders/export_vm_defaults.sh
bash cicd/builders/create_vm.sh
```

### CloudBuild variable escaping

```yaml
echo ${_BUCKET}         # CloudBuild substitution (build time)
echo $$MY_VAR           # Bash variable (runtime)
echo $${LOCAL_VAR}      # Bash variable in mixed context
```

### sed delimiters

Use `|` as default delimiter. For values containing `|`, use `#`:

```bash
sed -i "s|__AREA__|${_AREA}|g" /tmp/startup-script.sh
sed -i "s#__PIPE_VALUE__#${VALUE_WITH_PIPES}#g" /tmp/startup-script.sh
```

### Docker logging

All `docker run` commands should include `-e PYTHONUNBUFFERED=1` for real-time log output.

---

## Updating the Submodule

### Make changes to darwin-cicd

```bash
cd cicd/
# edit files...
git add -A && git commit -m "description of change"
git push origin main
```

### Update the pin in your project

```bash
cd ..  # back to project root
git add cicd
git commit -m "update cicd submodule"
```

### Get updates in another repo

```bash
cd cicd/
git pull origin main
cd ..
git add cicd
git commit -m "update cicd submodule"
```

### First-time clone (new developer)

```bash
git clone --recurse-submodules https://github.com/your-org/your-project.git
# OR if already cloned:
git submodule update --init --recursive
```
