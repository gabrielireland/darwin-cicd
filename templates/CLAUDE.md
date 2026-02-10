# Project Rules
<!--
  TEMPLATE from darwin-cicd (github.com/gabrielireland/darwin-cicd)

  HOW TO USE:
    1. Copy this file to your project root: cp cicd/templates/CLAUDE.md ./CLAUDE.md
    2. Sections 1-3 are UNIVERSAL — keep as-is, they enforce Darwin CI/CD standards
    3. Section 4 is PROJECT-SPECIFIC — fill in your pipelines, file structure, and domain rules
    4. Claude Code reads CLAUDE.md from the project root automatically

  UPDATING:
    When darwin-cicd updates this template, diff against your copy and merge new rules.
-->

<!-- ============================================================ -->
<!-- UNIVERSAL RULES — Do not modify (from darwin-cicd template)   -->
<!-- ============================================================ -->

## 1. CORE PRINCIPLES

### 1.1 No Hardcoding (CRITICAL)

| Never Hardcode | Instead |
|----------------|---------|
| Paths | Config files, CLI args, env vars |
| Feature names/indices | Read from `*_metadata.json` sidecars |
| Class names/mappings | Read from metadata JSON files |
| Magic numbers | Named constants or config |
| Year values | Pass as parameters |
| Bucket/region names | `cloudbuild-builds/config/defaults.yaml` + CloudBuild substitution variables |

### 1.2 Behavioral Rules

| Rule | Details |
|------|---------|
| **Git** | NEVER make commits - user handles all commits |
| **Execution** | Don't ask permission for: executing, changing code, editing files |
| **Decisions** | Ask when: multiple options exist, or more info improves output |
| **New Pipelines** | NEVER create new CloudBuild YAMLs unless explicitly asked |
| **Log Files** | User may provide `*logging*.txt` files for debugging. Only read when explicitly referenced |
| **No Dead Code** | After every change: delete unused variables, imports, "legacy" shims, commented-out code, backward-compat code that nothing uses. If it's not active, remove it. |

### 1.3 NEVER GIVE COMMANDS - MODIFY CONFIGS

**NEVER** give `gcloud builds submit --substitutions=...` commands.
**ALWAYS** edit the YAML file directly with desired parameters.

### 1.4 Keep CLAUDE.md Updated

Suggest additions when:
- Bug fixed that others might encounter
- New CI/CD gotcha discovered
- Default values change

**Never add to CLAUDE.md yourself** - suggest to user first.

### 1.5 Metadata Rules

**All metadata files MUST be JSON** (not YAML):
- `*_metadata.json` — per-file metadata
- `_run_contract.json` — run status, config, provenance, verification

**Metadata chain of custody**: metadata does NOT get disconnected at any moment. Downstream pipelines MUST read class definitions, feature names, and config from upstream metadata files — NOT from hardcoded values.

---

## 2. CLOUDBUILD RULES

### 2.1 Shell Strict Mode (REQUIRED)

**All scripts MUST start with:**

```bash
#!/bin/bash
set -euo pipefail
```

### 2.2 Variable Escaping (CRITICAL)

```yaml
# Single $  = CloudBuild substitution (BUILD time)
# Double $$ = Bash variable (RUNTIME)

echo ${_BUCKET}         # CloudBuild substitution
echo $$MY_VAR           # Bash variable
echo $${LOCAL_VAR}      # Bash variable in mixed context
```

### 2.3 Startup Script Placeholders

```bash
# prepare_vm_startup.sh handles common placeholders automatically:
#   __REGION__, __BUCKET__, __IMAGE_URI__, __VM_NAME__, __VM_ZONE__,
#   __BUILD_ID__, __GIT_COMMIT__, __CLOUDBUILD_YAML__, __PIPELINE_TITLE__

# Pipeline-specific: add sed in your YAML after calling prepare_vm_startup.sh
sed -i "s|__MY_PARAM__|${_MY_PARAM}|g" /tmp/startup-script.sh

# For values containing | use # delimiter:
sed -i "s#__PIPE_VALUE__#$$VALUE#g" /tmp/startup-script.sh
```

### 2.4 Bash Boolean to Python

```bash
# WRONG: python3 -c "first = ${FIRST_YEAR}"  → first = true (ERROR!)
# CORRECT:
PYTHON_BOOL=$([ "$FIRST_YEAR" = "true" ] && echo "True" || echo "False")
python3 -c "first = ${PYTHON_BOOL}"
```

### 2.5 Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `memory limit exceeded` | >32GB in Cloud Build | Use VM |
| `$VAR: unbound variable` | Single $ for bash var | Use $$ |
| `sed: can't read` | Pipe in value with \| delimiter | Use # delimiter |
| `true: command not found` | Bash bool in Python | Convert with $([ ]) |
| `tr '\n' not working` | Newline escape in YAML | Use `tr '\|' ' '` + loop |

### 2.6 Parsing Pipe-Delimited Strings (CRITICAL)

**NEVER use `tr '|' '\n'` in CloudBuild YAML** — `\n` is not interpreted as newline.

```yaml
# CORRECT - Use space delimiter + loop
VALUE=""
for MAPPING in $$(echo "${_MY_VAR}" | tr '|' ' '); do
  MAP_KEY=$$(echo "$$MAPPING" | cut -d'=' -f1)
  if [ "$$MAP_KEY" = "$$TARGET" ]; then
    VALUE=$$(echo "$$MAPPING" | cut -d'=' -f2)
    break
  fi
done
```

### 2.7 Docker Logging

**RULE**: All `docker run` commands MUST include `-e PYTHONUNBUFFERED=1`

### 2.8 Default Variables

**Single source of truth**: `cloudbuild-builds/config/defaults.yaml`

Builder scripts load defaults via the `cicd` submodule:
```bash
export DEFAULTS_FILE="cloudbuild-builds/config/defaults.yaml"
source cicd/config/load_defaults.sh
# Available as: CB_REGION, CB_BUCKET, CB_VM_SERVICE_ACCOUNT, CB_VM_ZONES, etc.
```

When changing a shared value, update `defaults.yaml` FIRST, then update all YAMLs to match.

### 2.9 Resource Limits

- Cloud Build: MAX 32GB memory
- Files >20GB: MUST use VM
- VM default: `n2-highmem-16` (128GB RAM)

### 2.10 GCS Upload Pattern

**RULE**: Python scripts do NOT upload to GCS directly. VM startup scripts handle all GCS uploads.

| Layer | Responsibility |
|-------|---------------|
| Python script | Write files to `/workspace_output/` |
| VM startup script | `gsutil -m rsync -r "$LOCAL_OUTPUT_DIR/" "$GCS_PATH/"` |

### 2.11 `cicd/` Submodule (CRITICAL)

Reusable CI/CD scripts live in **`darwin-cicd`**, consumed as a git submodule at `cicd/`.

| Rule | Details |
|------|---------|
| **`init-submodules` step** | MUST be the first step in every CloudBuild YAML |
| **`DEFAULTS_FILE` export** | MUST be set in every step that calls `cicd/` scripts |
| **`source` vs `bash`** | `export_vm_defaults.sh` MUST use `source`. All other scripts use `bash`. |
| **`VM_SCRIPTS_DIR`** | Tells `prepare_vm_startup.sh` where project VM scripts are (default: `cloudbuild-builds/vm`) |

**VM creation pattern (4 steps in order):**
```bash
bash cicd/builders/prepare_vm_startup.sh       # 1. Assemble + common sed
sed -i "s|__MY_PARAM__|value|g" /tmp/startup-script.sh  # 2. Pipeline-specific sed
source cicd/builders/export_vm_defaults.sh     # 3. Export VM defaults (MUST source)
bash cicd/builders/create_vm.sh                # 4. Create VM
```

See `cicd/docs/PIPELINE_GUIDE.md` for the complete template.

---

## 3. DOCKER RULES

### 3.1 Two-Layer Build Pattern

| Layer | File | Rebuilds when | Contains |
|-------|------|---------------|----------|
| Base | `Dockerfile.base` | Dependencies change | OS packages, Python packages, venv |
| Code | `Dockerfile` | Any commit | Application source code only |

**RULE**: `_UPDATE_BASE: 'false'` by default. Only set to `'true'` when `requirements.txt` or system dependencies change.

### 3.2 Docker Standards

- Base image: `python:3.10-slim` (or project-appropriate)
- Non-root user: Always create and switch to non-root user
- `PYTHONUNBUFFERED=1` in ENV
- `PYTHONPATH="/app"` in ENV
- Virtual environment at `/opt/venv`
- Application code at `/app`
- No cache: `pip install --no-cache-dir`

<!-- ============================================================ -->
<!-- PROJECT-SPECIFIC — Customize the sections below for your repo -->
<!-- ============================================================ -->

---

## 4. PROJECT: Pipelines
<!-- List your active pipelines here. Example:
| Stage | File | Purpose |
|-------|------|---------|
| 1 | `1-cloudbuild-feature-engineering.yaml` | Feature extraction |
| 2 | `2-cloudbuild-training.yaml` | Model training |
| 3 | `3-cloudbuild-prediction.yaml` | Inference |
-->

TODO: Add your pipeline table here.

---

## 5. PROJECT: File Structure
<!-- Document your repo's directory layout. Example:
```
├── 1-cloudbuild-*.yaml
├── cicd/                        # Submodule (do not edit)
├── cloudbuild-builds/
│   ├── config/defaults.yaml
│   ├── docker/{project}/
│   └── vm/
├── src/
└── configs/
```
-->

TODO: Add your file structure here.

---

## 6. PROJECT: Domain Rules
<!-- Add project-specific rules here. Examples:
- Metadata chain of custody specific to your pipeline stages
- Input file naming conventions
- Class definition workflow
- Feature naming conventions
- Any gotchas specific to your domain
-->

TODO: Add your domain-specific rules here.
