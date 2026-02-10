# darwin-cicd

Shared CI/CD scripts for CloudBuild VM pipelines. Consumed as a **git submodule** at `cicd/` — your project pins a specific version; CloudBuild clones it automatically via `init-submodules`.

**Get started**: [docs/SETUP.md](docs/SETUP.md) — add submodule, copy templates, configure defaults
**Create a pipeline**: [docs/PIPELINE_GUIDE.md](docs/PIPELINE_GUIDE.md) — full YAML + VM script template with checklist
**Update**: `cd cicd && git pull origin main && cd .. && git add cicd && git commit -m "update cicd"`

**Must-copy templates** (in [templates/](templates/)):

| File | Copy to | Purpose |
|------|---------|---------|
| `CLAUDE.md` | Project root | AI assistant rules — keeps Claude Code following Darwin standards |
| `Dockerfile.base` | `cloudbuild-builds/docker/` | Base image (deps, venv, non-root user) |
| `Dockerfile` | `cloudbuild-builds/docker/` | Code layer (app source, rebuilt every commit) |
| `requirements.txt` | `cloudbuild-builds/docker/` | Python packages starter |
