#!/usr/bin/env python3
"""
Self-test for cicd/utils/run_contract.py

Exercises the full contract lifecycle (init -> record-produced ->
mark-task -> preflight -> finalize) using only local temp files.
No GCS calls, no network, no mocks — just proves the tool runs
end-to-end and produces valid JSON with the expected schema.

Usage:  python3 cicd/tests/test_run_contract.py <cicd_root>
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run_cmd(cicd_root: Path, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(cicd_root / "utils" / "run_contract.py"), *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        msg = f"FAILED: {label}"
        if detail:
            msg += f" — {detail}"
        raise AssertionError(msg)
    print(f"  ok: {label}")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: test_run_contract.py <cicd_root>", file=sys.stderr)
        return 1

    cicd_root = Path(sys.argv[1]).resolve()
    rc_script = cicd_root / "utils" / "run_contract.py"
    if not rc_script.exists():
        print(f"run_contract.py not found at {rc_script}", file=sys.stderr)
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="rc_selftest_"))
    try:
        return _run_tests(cicd_root, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_tests(cicd_root: Path, tmp: Path) -> int:
    contract_file = tmp / "_run_contract.json"
    init_json = tmp / "init.json"
    expected_assets = [
        {
            "asset_id": "test/output_a",
            "kind": "cog",
            "role": "output",
            "required": True,
            "uri": "gs://fake-bucket/test/output_a.tif",
        },
        {
            "asset_id": "test/output_b",
            "kind": "manifest",
            "role": "output",
            "required": False,
            "uri": "gs://fake-bucket/test/output_b.jsonl",
        },
    ]
    init_json.write_text(json.dumps({
        "expected_assets": expected_assets,
        "config": {"test_key": "test_value"},
    }))

    # ---- 1. init ----
    r = run_cmd(
        cicd_root, "init",
        "--contract-file", str(contract_file),
        "--job-id", "selftest",
        "--run-id", "test-run-001",
        "--init-json-file", str(init_json),
    )
    check("init exits 0", r.returncode == 0, r.stderr)
    check("contract file created", contract_file.exists())

    contract = json.loads(contract_file.read_text())
    check("schema_version present", "schema_version" in contract)
    check("run section present", "run" in contract)
    check("assets is a list", isinstance(contract.get("assets"), list))
    check("2 assets registered", len(contract["assets"]) == 2,
          f"got {len(contract['assets'])}")

    # ---- 2. record-produced ----
    r = run_cmd(
        cicd_root, "record-produced",
        "--contract-file", str(contract_file),
        "--task-id", "selftest-task",
        "--asset-id", "test/output_a",
        "--uri", "gs://fake-bucket/test/output_a.tif",
    )
    check("record-produced exits 0", r.returncode == 0, r.stderr)

    contract = json.loads(contract_file.read_text())
    asset_a = next(a for a in contract["assets"] if a["asset_id"] == "test/output_a")
    check("asset marked produced", asset_a.get("produced") is True)

    # ---- 3. mark-task-succeeded ----
    r = run_cmd(
        cicd_root, "mark-task-succeeded",
        "--contract-file", str(contract_file),
        "--task-id", "selftest-task",
    )
    check("mark-task-succeeded exits 0", r.returncode == 0, r.stderr)

    contract = json.loads(contract_file.read_text())
    task = next(t for t in contract["tasks"] if t["task_id"] == "selftest-task")
    check("task status is succeeded", task["status"] == "succeeded")

    # ---- 4. preflight (no real GCS — inputs will show as unknown) ----
    r = run_cmd(
        cicd_root, "preflight",
        "--contract-file", str(contract_file),
    )
    check("preflight exits 0", r.returncode == 0, r.stderr)

    contract = json.loads(contract_file.read_text())
    check("preflight section present", "preflight" in contract)

    # ---- 5. finalize (no real GCS — assets will be missing/unknown) ----
    r = run_cmd(
        cicd_root, "finalize",
        "--contract-file", str(contract_file),
    )
    check("finalize exits 0", r.returncode == 0, r.stderr)

    contract = json.loads(contract_file.read_text())
    check("verification section present", "verification" in contract)
    v = contract["verification"]
    check("asset_status_counts present", "asset_status_counts" in v)
    check("finished_at present", "finished_at" in v)

    for asset in contract["assets"]:
        check(f"asset {asset['asset_id']} has status field", "status" in asset)
        check(f"asset {asset['asset_id']} has exists field", "exists" in asset)

    # ---- 6. JSON roundtrip integrity ----
    raw = contract_file.read_text()
    reparsed = json.loads(raw)
    re_serialized = json.dumps(reparsed, indent=2)
    reparsed_again = json.loads(re_serialized)
    check("JSON roundtrip stable", reparsed == reparsed_again)

    print("All run_contract self-tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
