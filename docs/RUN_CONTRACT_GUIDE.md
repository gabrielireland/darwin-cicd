# Run Contract Guide

## Purpose

`darwin-cicd` now includes a reusable run-contract utility that tracks:

- Which outputs are expected (from `job_id` + spec)
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
- `record-produced`
- `mark-task-running`
- `mark-task-succeeded`
- `mark-task-failed`
- `finalize`
- `cloud-run-env`

## 1) Define Expected Outputs by Job

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
  --var OUTPUT_DIR=/tmp/workspace_output \
  --var OUTPUT_GCS=gs://my-bucket/my-output-prefix
```

## 3) Record Outputs During Runtime (Optional)

```bash
bash cicd/utils/run_contract.sh record-produced \
  --contract-file /tmp/run_contract/_run_contract.json \
  --task-id train/${BUILD_ID} \
  --asset-id train/${BUILD_ID}/model \
  --kind model \
  --required true \
  --local-path /tmp/workspace_output/model.pkl
```

## 4) Finalize (Expected vs Actual Audit)

```bash
bash cicd/utils/run_contract.sh finalize \
  --contract-file /tmp/run_contract/_run_contract.json \
  --scan-local-dir /tmp/workspace_output \
  --scan-gcs-prefix gs://my-bucket/my-output-prefix \
  --upload-gcs-dir gs://my-bucket/my-output-prefix \
  --strict
```

`--strict` exits with code `2` when required outputs are missing/corrupt/unverified.

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

- `write_run_contract`
- `update_run_contract`

If the CLI is not available in the runtime environment, it automatically falls back to the legacy `_run_contract.json` behavior.
