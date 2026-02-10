# darwin-cicd

Reusable CI/CD scripts for Google CloudBuild VM-based pipelines.

Handles Docker image builds, VM creation with zone fallback, startup script assembly, and Cloud Logging integration. Designed to be consumed as a **git submodule**.

## Guides

- **[Setup Guide](docs/SETUP.md)** — Add this module to your project
- **[Pipeline Guide](docs/PIPELINE_GUIDE.md)** — Create a new CloudBuild VM pipeline from scratch

## What's included

```
cicd/
├── config/
│   └── load_defaults.sh           # Parses defaults.yaml → CB_* env vars
├── builders/
│   ├── build_base_image_step.sh   # Docker base image (call with bash)
│   ├── build_base_image.sh        #   └── standalone builder
│   ├── build_code_image_step.sh   # Docker code layer (call with bash)
│   ├── build_code_image.sh        #   └── standalone builder
│   ├── prepare_vm_startup.sh      # Assemble startup script + common sed (call with bash)
│   ├── export_vm_defaults.sh      # Export VM config (call with source, NOT bash)
│   ├── create_vm.sh               # Create VM with zone fallback + logging link (call with bash)
│   └── print_logging_link.sh      # Print Cloud Logging URL (call with bash)
├── utils/
│   ├── preflight_check.sh         # GCS validation (concatenated into VM scripts)
│   └── startup_common.sh          # Docker auth + pull (concatenated into VM scripts)
└── docs/
    ├── SETUP.md
    └── PIPELINE_GUIDE.md
```

## Quick start

```bash
# 1. Add to your project
git submodule add https://github.com/gabrielireland/darwin-cicd.git cicd

# 2. Create your defaults config
#    See docs/SETUP.md for the full defaults.yaml format

# 3. Create your pipeline
#    See docs/PIPELINE_GUIDE.md for the complete YAML + VM script template
```

## How it works

```
Your project                          cicd/ submodule
─────────────                         ────────────────
defaults.yaml ──DEFAULTS_FILE──> load_defaults.sh ──> CB_REGION, CB_BUCKET, ...
                                                            │
CloudBuild YAML ──_REGION──> builder scripts use: ${_REGION:-${CB_REGION}}
                             (CloudBuild substitution wins, then defaults)
```

Every CloudBuild step that calls `cicd/` scripts must export `DEFAULTS_FILE` pointing to your project's `defaults.yaml`.

## Updating

```bash
# Pull latest changes
cd cicd && git pull origin main && cd ..

# Pin the new version in your project
git add cicd && git commit -m "update cicd submodule"
```
