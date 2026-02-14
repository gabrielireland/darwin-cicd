# darwin-cicd

Shared CI/CD scripts for CloudBuild VM pipelines. Consumed as a **git submodule** at `cicd/` — your project pins a specific version; CloudBuild clones it automatically via `init-submodules`.

**Get started**: [docs/SETUP.md](docs/SETUP.md) — add submodule, copy templates, configure defaults
**Create a pipeline**: [docs/PIPELINE_GUIDE.md](docs/PIPELINE_GUIDE.md) — full YAML + VM script template with checklist
**Run contracts**: [docs/RUN_CONTRACT_GUIDE.md](docs/RUN_CONTRACT_GUIDE.md) — expected vs actual output audit (local/VM/Cloud Run)
**Update**: `cd cicd && git pull origin main && cd .. && git add cicd && git commit -m "update cicd"`

**Must-copy templates** (in [templates/](templates/)):

| File | Copy to | Purpose |
|------|---------|---------|
| `CLAUDE.md` | Project root | AI assistant rules — keeps Claude Code following Darwin standards |
| `AGENTS.md` | Project root | AI assistant rules (AGENTS flavor) |
| `Dockerfile.base` | `cloudbuild-builds/docker/` | Base image (deps, venv, non-root user) |
| `Dockerfile` | `cloudbuild-builds/docker/` | Code layer (app source, rebuilt every commit) |
| `requirements.txt` | `cloudbuild-builds/docker/` | Python packages starter |
| `run_contract_jobs.example.json` | `cloudbuild-builds/config/run_contract_jobs.json` | Job-id based expected outputs map |

---

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
│   ├── create_multi_vms.sh        # Create 1..N VMs with zone fallback + logging links
│   └── print_logging_link.sh      # Print Cloud Logging URL (call with bash)
├── utils/
│   ├── preflight_check.sh         # GCS validation (concatenated into VM scripts)
│   ├── startup_common.sh          # Docker auth + pull (concatenated into VM scripts)
│   ├── run_contract.sh            # Shell entrypoint for run-contract CLI
│   └── run_contract.py            # Expected-vs-actual output auditor
├── templates/
│   ├── CLAUDE.md                  # AI assistant rules template
│   ├── AGENTS.md                  # AI assistant rules template
│   ├── Dockerfile.base            # Base image template
│   ├── Dockerfile                 # Code layer template
│   ├── requirements.txt           # Common Python packages
│   └── run_contract_jobs.example.json
└── docs/
    ├── SETUP.md
    ├── PIPELINE_GUIDE.md
    └── RUN_CONTRACT_GUIDE.md
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
