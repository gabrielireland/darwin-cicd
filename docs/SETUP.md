# Adding darwin-cicd to Your Project

## 1. Add the submodule

```bash
git submodule add https://github.com/gabrielireland/darwin-cicd.git cicd
git commit -m "Add darwin-cicd submodule"
```

This creates:
- `cicd/` — the submodule folder (all scripts)
- `.gitmodules` — git submodule config

## 2. Create your project config

```bash
mkdir -p cloudbuild-builds/config
```

Create `cloudbuild-builds/config/defaults.yaml`:

```yaml
# Infrastructure
region: 'europe-west1'
bucket: 'my-gcs-bucket'
service_account: 'projects/my-project/serviceAccounts/sa@my-project.iam.gserviceaccount.com'
vm_service_account: 'sa@my-project.iam.gserviceaccount.com'

# Docker
dockerfile_base_path: 'cloudbuild-builds/docker/Dockerfile.base'
dockerfile_code_path: 'cloudbuild-builds/docker/Dockerfile'
base_image_name: 'my-base-image'

# VM
vm_zones: 'europe-west1-d,europe-west1-c,europe-west1-b'
boot_disk_size: '200GB'
update_base: 'false'
```

## 3. Copy templates

```bash
# AI assistant rules (ensures Claude Code follows Darwin CI/CD patterns)
cp cicd/templates/CLAUDE.md ./CLAUDE.md

# Docker files
mkdir -p cloudbuild-builds/docker/my_project
cp cicd/templates/Dockerfile.base cloudbuild-builds/docker/my_project/
cp cicd/templates/Dockerfile cloudbuild-builds/docker/my_project/
cp cicd/templates/requirements.txt cloudbuild-builds/docker/my_project/

# Optional: run-contract expectations (expected outputs by job_id)
cp cicd/templates/run_contract_jobs.example.json cloudbuild-builds/config/run_contract_jobs.json
```

Edit each file to match your project (update paths, add dependencies, customize CLAUDE.md).

## 4. Create your project directories

```
my-project/
├── CLAUDE.md                          # AI rules (from template)
├── cicd/                              # Submodule (do not edit directly)
├── cloudbuild-builds/
│   ├── config/defaults.yaml           # Your project defaults
│   ├── docker/my_project/
│   │   ├── Dockerfile.base            # Base image (from template)
│   │   ├── Dockerfile                 # Code layer (from template)
│   │   └── requirements.txt           # Python deps (from template)
│   └── vm/                            # VM startup scripts (one per pipeline)
│       └── my_pipeline.sh
└── my-pipeline.yaml                   # CloudBuild YAML
```

## 5. Verify setup

```bash
# Check submodule is initialized
git submodule status
# Should show: <commit-hash> cicd (heads/main)

# Check defaults load correctly
export DEFAULTS_FILE="cloudbuild-builds/config/defaults.yaml"
source cicd/config/load_defaults.sh
echo $CB_REGION   # Should print: europe-west1
echo $CB_BUCKET   # Should print: my-gcs-bucket
```

## 6. For new team members

After cloning the project:

```bash
git submodule update --init --recursive
```

Or clone with submodules in one step:

```bash
git clone --recurse-submodules https://github.com/your-org/your-project.git
```

## 7. Updating the submodule

When `darwin-cicd` has new updates:

```bash
cd cicd
git pull origin main
cd ..
git add cicd
git commit -m "Update cicd submodule"
```
