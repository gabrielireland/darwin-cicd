#!/usr/bin/env python3
"""Shared internal utilities for data_engineering module."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _atomic_write_json(path: Path, payload: Any, indent: int = 2) -> None:
    """Atomic JSON write via tmp + rename. Matches run_contract.py pattern."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=indent, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _load_json_file(path: Path) -> Any:
    """Load and parse a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _open_zarr_store(zarr_path: str, mode: str = "r"):
    """Open a zarr store, trying consolidated metadata first."""
    import zarr

    if mode == "r":
        try:
            return zarr.open_consolidated(zarr_path, mode=mode)
        except Exception:
            pass
    return zarr.open(zarr_path, mode=mode)
