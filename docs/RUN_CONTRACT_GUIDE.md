# Run Contract Guide

## Purpose

`darwin-cicd` includes a reusable run-contract utility that tracks:

- Which **inputs** are expected and whether they exist before processing
- Which **outputs** are expected (from `job_id` + spec)
- Which outputs were produced
- Which required outputs are missing/corrupt/unverified
- Which unexpected outputs exist in scanned output paths

This follows the same expected-vs-actual reporting logic in a generic form for any pipeline.

## Two-Layer Observability Model

Run contracts operate at the **infrastructure layer** — they verify that expected files exist, detect corruption, and upload per-folder contracts to GCS. They are pipeline-agnostic and work the same for any pipeline.

Application-level reporting (e.g., task execution logs, timing, error details) is the responsibility of the **pipeline's own code**. This is intentionally separate:

| Layer | Responsibility | Tool | Output |
|-------|---------------|------|--------|
| **Infrastructure** (cicd) | Asset existence, corruption detection, per-folder contracts | `run_contract.py` | `_run_contract.json` |
| **Application** (pipeline) | Task lifecycle, execution timing, error context, produced assets | Pipeline-specific | `run_tasks.jsonl`, `run_summary.json`, etc. |

**Rules:**
- Infrastructure verification (file scanning, corruption detection) belongs ONLY in the run contract
- Application code should NOT duplicate existence checks or corruption detection
- The run contract does NOT need to know about pipeline business logic (indicator names, AOI processing, etc.)
- Both layers write to their own files; they do not merge

## Critical Rule: Never Pass JSON Through Shell

**All JSON arguments MUST be passed as files, never as inline strings.**

Shell argument chains (`$()`, function params, `echo`, `cat`) introduce invisible characters
that corrupt JSON — even when intermediate validation passes.

**Standard pattern:**
1. Python writes JSON to temp files
2. `run_contract.py` reads files via `--*-file` flags
3. Shell only passes file **paths** (never content)

## Files Written Per Run

The tool writes a single `_run_contract.json`. By default (with `--contract-scope folder`), finalize uploads a **per-folder** contract to each GCS output folder, so every subfolder has its own `_run_contract.json` sitting next to the data it describes.

- Local: `${CONTRACT_FILE}` (full contract with all tasks/assets)
- GCS: `{folder_uri}/_run_contract.json` per output folder (filtered to that folder's assets)

## CLI Entry Point

On VMs, `prepare_vm_startup.sh` embeds `run_contract.py` into the startup script.
Resolve the CLI path with the helper function:

```bash
RUN_CONTRACT_CLI="$(run_contract_cli_path)"
```

Then call directly:

```bash
"${RUN_CONTRACT_CLI}" <subcommand> [--flags...]
```

Subcommands:

- `init`
- `preflight`
- `record-produced`
- `mark-task-running`
- `mark-task-succeeded`
- `mark-task-failed`
- `finalize`
- `cloud-run-env`

## 1) Define Expected Inputs and Outputs by Job

Create a JSON spec with a `jobs` map. Use `templates/run_contract_jobs.example.json` as the starter template.

Minimal schema:

```json
{
  "jobs": {
    "my-job-id": {
      "tasks": [
        {
          "task_id": "train/${RUN_ID}",
          "labels": {"stage": "train"},
          "expected_inputs": [
            {
              "asset_id": "features",
              "kind": "tensor",
              "required": true,
              "uri": "gs://${BUCKET}/${FEATURES_PATH}/features_${YEAR}.pt"
            }
          ],
          "expected_assets": [
            {
              "asset_id": "train/${RUN_ID}/model",
              "kind": "model",
              "required": true,
              "local_path": "${OUTPUT_DIR}/model.pkl"
            }
          ]
        }
      ]
    }
  }
}
```

Every asset (input or output) gets a `role` field automatically:

- `expected_inputs` entries get `role: "input"`
- `expected_assets` entries get `role: "output"`

Supported asset location fields:

- `local_path`
- `uri` (`gs://...`)
- `local_glob`
- `gcs_glob`

## 2) Initialize Contract

Use Python to write a single JSON file, then pass its path to the CLI:

```bash
# ---- Python writes one JSON file (shell never touches JSON) ----
INIT_JSON="/tmp/contract_init.json"

python3 -c "
import json, sys, pathlib

job_config, output_prefix, image_uri, bucket, build_id = sys.argv[1:6]
out = pathlib.Path(sys.argv[6])

contract = {
    'config': {
        'job_config': job_config,
        'output_prefix': output_prefix,
        'image_uri': image_uri,
        'target_bucket': bucket
    },
    'inputs': {
        'source': 'description of input source'
    },
    'expected_assets': [
        {'asset_id': 'cog_outputs', 'kind': 'output', 'required': True,
         'gcs_glob': f'gs://{bucket}/{output_prefix}/**/*.tif'}
    ],
    'run_metadata': {
        'vm_name': 'my-vm',
        'build_id': build_id
    }
}

out.write_text(json.dumps(contract, indent=2))
" "${JOB_CONFIG}" "${OUTPUT_PREFIX}" "${IMAGE_URI}" "${BUCKET}" "${BUILD_ID}" "${INIT_JSON}"

# ---- Call run_contract.py with single init file ----
RUN_CONTRACT_CLI="$(run_contract_cli_path)"

"${RUN_CONTRACT_CLI}" init \
  --contract-file "${CONTRACT_FILE}" \
  --job-id "${PIPELINE_TITLE:-pipeline}" \
  --run-id "${BUILD_ID:-}" \
  --pipeline-title "${PIPELINE_TITLE:-pipeline}" \
  --output-location "${OUTPUT_GCS}" \
  --init-json-file "${INIT_JSON}" \
  --upload-gcs-dir "${OUTPUT_GCS}"
```

The `--upload-gcs-dir` flag uploads the contract to GCS immediately after init, so there's a record of what was expected even if the VM crashes mid-run.

The `--init-json-file` accepts a single JSON object with these keys:

| Key | Content |
|-----|---------|
| `config` | Pipeline config (job, image, bucket, etc.) |
| `inputs` | Input sources description |
| `expected_assets` | Array of expected output assets |
| `run_metadata` | VM name, build ID, commit SHA, etc. |

Individual `--*-json-file` flags (`--config-json-file`, `--inputs-json-file`, etc.) still work and override keys from `--init-json-file`.

The init summary shows the input/output breakdown:

```
tasks=1 assets=3 (inputs=1 outputs=2)
```

## 3) Preflight Check

Verify all input assets exist before processing starts:

```bash
bash cicd/utils/run_contract.sh preflight \
  --contract-file /tmp/run_contract/_run_contract.json \
  --strict
```

Output:

```
  [OK]      features                       gs://bucket/features_2023.pt
  [MISSING] labels                         gs://bucket/labels_2023.pt  (required)
run_contract preflight: /tmp/run_contract/_run_contract.json
total_inputs=2 ok=1 missing_required=1 missing_optional=0
```

Flags:

- `--strict`: exit with code `2` if any required inputs are missing
- `--upload-gcs-dir`: upload contract bundle to GCS after preflight

The preflight results are saved to the contract under `contract.preflight`.

## 4) Record Outputs During Runtime (Optional)

```bash
bash cicd/utils/run_contract.sh record-produced \
  --contract-file /tmp/run_contract/_run_contract.json \
  --task-id train/${BUILD_ID} \
  --asset-id train/${BUILD_ID}/model \
  --kind model \
  --required true \
  --local-path /tmp/workspace_output/model.pkl
```

## 5) Finalize (Expected vs Actual Audit + GCS Upload)

Write verification data via Python, then call finalize. Finalize audits all assets, uploads per-folder contracts to GCS, and writes the final local contract.

```bash
# ---- Python writes verification JSON ----
python3 -c "
import json, sys, pathlib
pathlib.Path(sys.argv[3]).write_text(json.dumps({
    'exit_code': int(sys.argv[1]),
    'duration_seconds': int(sys.argv[2])
}))
" "${EXIT_CODE}" "${DURATION}" "${JSON_TMP}/verification.json"

# ---- Finalize with per-folder contracts ----
"${RUN_CONTRACT_CLI}" finalize \
  --contract-file "${CONTRACT_FILE}" \
  --status "${STATUS}" \
  --output-location "${OUTPUT_GCS}" \
  --contract-scope folder \
  --verification-json-file "${JSON_TMP}/verification.json"
```

**`--contract-scope`** controls how contracts are uploaded to GCS:

| Scope | Behavior |
|-------|----------|
| `folder` (default) | Groups assets by GCS folder, uploads a filtered `_run_contract.json` to each folder |
| `run` | Uploads one `_run_contract.json` to the output root |

`--strict` exits with code `2` when required outputs are missing/corrupt/unverified.

Finalize reports input and output status separately:

```
  uploaded: gs://bucket/jaen/ndvi/_run_contract.json (2 assets)
run_contract finalize: /tmp/work/_run_contract.json
required_missing=0 required_corrupt=0 required_unverified=0
output_assets={'ok': 2}
```

The verification object includes `input_asset_status_counts`, `output_asset_status_counts`, `missing_required_input_ids`, and `folder_uploads`.

## Cloud Run Configuration Helper

Generate env values for Cloud Run/Cloud Run Jobs:

```bash
bash cicd/utils/run_contract.sh cloud-run-env \
  --job-id my-job-id \
  --spec-file /app/cloudbuild-builds/config/run_contract_jobs.json \
  --gcs-run-dir gs://my-bucket/run-reports/my-job-id \
  --format set-env-vars
```

Formats:

- `dotenv`
- `shell`
- `set-env-vars`
- `json`

## 6) GCS Upload (Handled by Finalize)

**No manual `gsutil cp` is needed.** Finalize handles all GCS uploads internally based on `--contract-scope`.

With `--contract-scope folder` (default), each output folder gets its own `_run_contract.json`:
```
gs://bucket/jaen/ndvi/_run_contract.json    (only ndvi assets)
```

With `--contract-scope run`, one contract is uploaded to the output root:
```
gs://bucket/jaen/_run_contract.json         (all assets)
```

Upload results are stored in `verification.folder_uploads` on the local contract.

## Output Naming: Single Source of Truth (CRITICAL)

The pipeline that **produces** an output is the **only** authority on its filename, path, and count. No other layer (orchestrator, VM script, config template) may independently construct output names.

**Why**: When naming logic is duplicated, the run contract declares expected files that don't match what the pipeline actually writes. Verification then reports false negatives (files marked missing that actually exist under different names), breaking the entire observability chain.

### Rules

| Rule | Details |
|------|---------|
| **Pipeline owns naming** | The code that writes a file is the single source of truth for its name, extension, and path structure. This applies to any format: `.tif`, `.zarr`, `.cog`, `.parquet`, `.json`, etc. |
| **Contract consumes, never invents** | The run contract receives expected asset definitions from the pipeline — it never constructs filenames on its own. |
| **No parallel naming logic** | If an orchestrator, config layer, or VM script needs to know output names before execution, it must ask the pipeline (via a method, a manifest, or a pre-declared schema) — not re-derive them independently. |
| **Multi-output awareness** | Pipelines that produce multiple files per task (e.g., per-band, per-tile, per-chunk) must declare all individual outputs as separate expected assets. A single glob is acceptable for verification, but expected assets must reflect the actual file count and naming. |

### Pattern: Pipeline Declares Expected Assets

The pipeline (or its indicator/processor) exposes a function that returns the list of expected output assets **before** execution starts. The orchestrator calls this function and passes the result to `run_contract.py init`.

```
┌────────────┐    "what will you produce?"    ┌──────────┐
│ Orchestrator│ ──────────────────────────────>│ Pipeline  │
│             │ <──────────────────────────────│           │
│             │    [asset_id, uri, kind, ...]  │           │
│             │                                │           │
│  passes to  │                                │  writes   │
│  run_contract init                           │  files    │
└────────────┘                                 └──────────┘
```

**Never** do this:
```python
# WRONG — orchestrator guesses the filename
filename = f"{variable}_{year}_{season}_{aoi}.tif"
```

**Always** do this:
```python
# CORRECT — pipeline declares its own outputs
expected_assets = pipeline.get_expected_assets(ctx)
# returns: [{"asset_id": "...", "kind": "cog", "required": True, "uri": "gs://...b02...tif"}, ...]
```

### `get_expected_assets(ctx)` Method Contract

Every pipeline MUST implement `get_expected_assets(ctx)` that returns the full list of expected outputs **before** execution. Each entry is a dict with:

| Key | Required | Description |
|-----|----------|-------------|
| `asset_id` | Yes | Unique ID within the task (e.g., `jaen/ndvi/2019/aug/cog`) |
| `kind` | Yes | Asset type: `cog`, `metadata`, `manifest`, etc. |
| `required` | Yes | Whether the asset MUST be present for the run to be valid |
| `uri` | One of uri/local_path | GCS URI (`gs://...`) |
| `local_path` | One of uri/local_path | Local filesystem path |

**Static pipelines** (output count known from config): declare all outputs. Example — per-band pipeline declares one COG per band, one metadata per band, one manifest.

**Dynamic pipelines** (output count discovered at runtime): declare only what's known upfront (e.g., the manifest). Individual outputs are registered via `record-produced` during execution.

### End-to-End Example: Contract as the Dictionary (CRITICAL)

The run contract is the **dictionary** — once initialized, every layer reads paths FROM it. No layer ever constructs paths on the fly.

**Step A — Pipeline lists all files it will produce:**

```python
# The pipeline knows its own naming. Ask it BEFORE execution.
assets = pipeline.get_expected_assets(ctx)
# Returns:
# [
#   {"asset_id": "jaen/ndvi/2019/aug/cog",      "kind": "cog",      "required": True,  "uri": "gs://bucket/ndvi/ndvi_2019_aug_jaen.tif"},
#   {"asset_id": "jaen/ndvi/2019/aug/metadata",  "kind": "metadata", "required": False, "uri": "gs://bucket/ndvi/ndvi_2019_aug_jaen.json"},
#   {"asset_id": "jaen/ndvi/2019/aug/manifest",  "kind": "manifest", "required": False, "uri": "gs://bucket/ndvi/manifest_ndvi_2019_aug_jaen.jsonl"},
# ]
```

**Step B — Initialize the run contract with those assets:**

```python
# Write the contract init file — this IS the dictionary
import json, pathlib
pathlib.Path("/tmp/contract_init.json").write_text(json.dumps({
    "expected_assets": assets,   # <-- straight from the pipeline
    "config": { ... },
    "run_metadata": { ... },
}))
```

```bash
"${RUN_CONTRACT_CLI}" init \
  --contract-file "${CONTRACT_FILE}" \
  --job-id "ndvi" \
  --run-id "${BUILD_ID}" \
  --init-json-file "/tmp/contract_init.json" \
  --upload-gcs-dir "${OUTPUT_GCS}"
```

**Step C — During execution, read paths FROM the contract, never build them:**

```python
# WRONG — building a path on the fly
output_path = f"gs://{bucket}/{prefix}/ndvi_2019_aug_jaen.tif"

# CORRECT — the contract already knows every path
contract = json.loads(Path(contract_file).read_text())
for asset in contract["assets"]:
    if asset["kind"] == "cog":
        output_path = asset["uri"]  # <-- read from the dictionary
```

**Step D — Finalize verifies the dictionary against reality:**

```bash
"${RUN_CONTRACT_CLI}" finalize \
  --contract-file "${CONTRACT_FILE}" \
  --status "${STATUS}" \
  --contract-scope folder
# Reports: required_missing=0 required_corrupt=0
```

**The rule is simple**: paths are born in `get_expected_assets()`, written to the contract, and read from the contract. They are never invented anywhere else.

### Anti-Patterns

| Anti-Pattern | Consequence |
|---|---|
| Orchestrator constructs filenames using its own template | Names diverge when pipeline changes naming (e.g., adds band prefix) |
| Config YAML contains hardcoded output paths | Config and pipeline drift apart silently |
| VM startup script builds expected asset URIs from substitution variables | Third place where naming logic lives, triple the drift risk |
| Single expected asset declared for a pipeline that produces N files | Verification cannot track individual outputs |

## Pipeline Lifecycle (Standard for All Pipelines)

Every VM startup script MUST follow this 3-stage pattern:

```bash
# ========== STAGE 1: DECLARE RUN CONTRACT ==========
# Python writes one JSON file. Shell never touches JSON content.
INIT_JSON="/tmp/contract_init.json"

python3 -c "
import json, sys, pathlib
# ... write single JSON with config, inputs, expected_assets, run_metadata
" args... "${INIT_JSON}"

RUN_CONTRACT_CLI="$(run_contract_cli_path)"

"${RUN_CONTRACT_CLI}" init \
  --contract-file "${CONTRACT_FILE}" \
  --job-id "${PIPELINE_TITLE:-pipeline}" \
  --run-id "${BUILD_ID:-}" \
  --pipeline-title "${PIPELINE_TITLE:-pipeline}" \
  --output-location "${OUTPUT_GCS}" \
  --init-json-file "${INIT_JSON}" \
  --upload-gcs-dir "${OUTPUT_GCS}"

# (Optional) Preflight — verify inputs exist
# "${RUN_CONTRACT_CLI}" preflight --contract-file "${CONTRACT_FILE}" --strict

# ========== STAGE 2: RUN THE PIPELINE ==========
docker run --rm ... 2>&1 | tee "${LOG_FILE}"
EXIT_CODE=${PIPESTATUS[0]}

# ========== STAGE 3: FINALIZE ==========
if [ "${EXIT_CODE}" -eq 0 ]; then STATUS="COMPLETE"; else STATUS="FAILED"; fi

python3 -c "
import json, sys, pathlib
pathlib.Path(sys.argv[3]).write_text(json.dumps({
    'exit_code': int(sys.argv[1]),
    'duration_seconds': int(sys.argv[2])
}))
" "${EXIT_CODE}" "${DURATION}" "${JSON_TMP}/verification.json"

"${RUN_CONTRACT_CLI}" finalize \
  --contract-file "${CONTRACT_FILE}" \
  --status "${STATUS}" \
  --output-location "${OUTPUT_GCS}" \
  --contract-scope folder \
  --verification-json-file "${JSON_TMP}/verification.json"
# Finalize uploads per-folder contracts to GCS automatically.
```

## Migration from preflight_check.sh

The standalone `preflight_check.sh` remains available as a fallback. To migrate a pipeline:

**Before** (standalone bash checks):
```bash
source cicd/utils/preflight_check.sh
preflight_validate_gcs "gs://bucket/features.pt" "features file"
preflight_validate_gcs "gs://bucket/labels.pt" "labels file"
```

**After** (contract-integrated, file-based):
```bash
# Python writes expected inputs to a file
python3 -c "
import json, pathlib
pathlib.Path('/tmp/contract_args/expected_inputs.json').write_text(json.dumps([
    {'asset_id': 'features', 'kind': 'tensor', 'required': True, 'uri': 'gs://bucket/features.pt'},
    {'asset_id': 'labels', 'kind': 'tensor', 'required': True, 'uri': 'gs://bucket/labels.pt'}
]))
"

# Init with file-based args
"${RUN_CONTRACT_CLI}" init \
  --contract-file "${CONTRACT_FILE}" \
  --job-id "my-pipeline" \
  --run-id "${BUILD_ID}" \
  --expected-assets-file "/tmp/contract_args/expected_inputs.json" \
  --upload-gcs-dir "${OUTPUT_GCS}" \
  ...

# Preflight
"${RUN_CONTRACT_CLI}" preflight --contract-file "${CONTRACT_FILE}" --strict
```

The contract approach gives you structured tracking, per-asset status in the contract JSON, and a unified audit trail for both inputs and outputs.
