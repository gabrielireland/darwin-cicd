# Run Contract Guide

## Purpose

`darwin-cicd` now includes a reusable run-contract utility that tracks:

- Which **inputs** are expected and whether they exist before processing
- Which **outputs** are expected (from `job_id` + spec)
- Which outputs were produced
- Which required outputs are missing/corrupt/unverified
- Which unexpected outputs exist in scanned output paths

This follows the same expected-vs-actual reporting logic used in `spatial_data_mining`, but in a generic form for any pipeline.

## Files Written Per Run

Given a run directory (default: `run_contracts/<job_id>/<run_id>/`), the tool writes:

- `_run_contract.json`: full contract
- `run_tasks.jsonl`: `run` / `task` / `asset` records
- `run_summary.json`: compact status summary

## CLI Entry Point

Use:

```bash
bash cicd/utils/run_contract.sh <subcommand> ...
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

```bash
bash cicd/utils/run_contract.sh init \
  --job-id my-job-id \
  --run-id "${BUILD_ID}" \
  --spec-file cloudbuild-builds/config/run_contract_jobs.json \
  --run-dir /tmp/run_contract \
  --output-location "gs://my-bucket/my-output-prefix" \
  --expected-inputs-json '[{"asset_id":"features","kind":"tensor","required":true,"uri":"gs://bucket/features.pt"}]' \
  --expected-assets-json '[{"asset_id":"model","kind":"model","required":true,"local_path":"/tmp/out/model.pkl"}]' \
  --var OUTPUT_DIR=/tmp/workspace_output \
  --var OUTPUT_GCS=gs://my-bucket/my-output-prefix
```

Input assets can be provided via:

- `--expected-inputs-json` (inline JSON array)
- `--expected-inputs-file` (path to JSON file containing an array)
- `expected_inputs` in the spec file task definition

The init summary now shows the input/output breakdown:

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

## 5) Finalize (Expected vs Actual Audit)

```bash
bash cicd/utils/run_contract.sh finalize \
  --contract-file /tmp/run_contract/_run_contract.json \
  --scan-local-dir /tmp/workspace_output \
  --scan-gcs-prefix gs://my-bucket/my-output-prefix \
  --upload-gcs-dir gs://my-bucket/my-output-prefix \
  --strict
```

`--strict` exits with code `2` when required outputs are missing/corrupt/unverified.

Finalize now reports input and output status separately:

```
required_missing=1 required_corrupt=0 required_unverified=0
input_assets={'ok': 2}
output_assets={'ok': 3, 'missing': 1}
```

The verification object includes `input_asset_status_counts`, `output_asset_status_counts`, and `missing_required_input_ids`.

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

## Compatibility with Existing VM Helpers

`utils/startup_common.sh` now tries to use this CLI in:

- `write_run_contract` (6th parameter: `EXPECTED_INPUTS_JSON`)
- `preflight_run_contract` (new)
- `update_run_contract`

If the CLI is not available in the runtime environment, it automatically falls back to the legacy `_run_contract.json` behavior.

## Pipeline Lifecycle (New Standard)

```bash
# 1. Init — declare inputs + outputs
write_run_contract "$CONTRACT_FILE" "$OUTPUT_GCS" \
  "$CONFIG_JSON" "$INPUTS_JSON" "$EXPECTED_OUTPUTS_JSON" "$EXPECTED_INPUTS_JSON"

# 2. Preflight — verify inputs exist
preflight_run_contract "$CONTRACT_FILE" --strict

# 3. Processing
docker run ...

# 4. Finalize — verify outputs exist
update_run_contract "$CONTRACT_FILE" "$OUTPUT_GCS" "$STATUS" "$VERIFICATION_JSON"
```

## Migration from preflight_check.sh

The standalone `preflight_check.sh` remains available as a fallback. To migrate a pipeline:

**Before** (standalone bash checks):
```bash
source cicd/utils/preflight_check.sh
preflight_validate_gcs "gs://bucket/features.pt" "features file"
preflight_validate_gcs "gs://bucket/labels.pt" "labels file"
```

**After** (contract-integrated):
```bash
write_run_contract "$CONTRACT_FILE" "$OUTPUT_GCS" \
  "$CONFIG_JSON" "$INPUTS_JSON" "$EXPECTED_OUTPUTS_JSON" \
  '[{"asset_id":"features","kind":"tensor","required":true,"uri":"gs://bucket/features.pt"},
    {"asset_id":"labels","kind":"tensor","required":true,"uri":"gs://bucket/labels.pt"}]'

preflight_run_contract "$CONTRACT_FILE" --strict
```

The contract approach gives you structured tracking, per-asset status in the contract JSON, and a unified audit trail for both inputs and outputs.
