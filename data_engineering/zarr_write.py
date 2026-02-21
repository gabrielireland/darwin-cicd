#!/usr/bin/env python3
"""
Safely write/append data to zarr stores with schema validation.

Provides:
  - write_variable: write data to a variable (full or partial via slices)
  - append_along_dimension: append data along an appendable dimension
  - write_store_attrs: merge or replace root-level .zattrs
  - safe_write_variable: crash-safe backup-write-verify-swap
  - consolidate: consolidate zarr metadata for cloud access

All heavy imports are lazy (inside functions).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from .schema import ZarrSchema


def _validate_data_for_variable(
    data: Any,
    variable_name: str,
    schema: ZarrSchema,
    *,
    partial_dims: Optional[Dict[str, int]] = None,
) -> None:
    """Check data dtype and shape against schema. Raises ValueError on mismatch."""
    import numpy as np

    var = schema.get_variable(variable_name)
    if var is None:
        raise ValueError(
            f"Variable '{variable_name}' not found in schema. "
            f"Available: {[v.name for v in schema.variables]}"
        )

    arr = np.asarray(data)

    # Dtype check
    expected_dtype = np.dtype(var.dtype)
    if arr.dtype != expected_dtype:
        if not np.can_cast(arr.dtype, expected_dtype, casting="safe"):
            raise ValueError(
                f"Variable '{variable_name}': dtype {arr.dtype} cannot be "
                f"safely cast to schema dtype {expected_dtype}"
            )

    # Shape check (only for dimensions with known size)
    if arr.ndim != len(var.dims):
        raise ValueError(
            f"Variable '{variable_name}': data has {arr.ndim} dimensions, "
            f"schema expects {len(var.dims)} ({var.dims})"
        )

    for i, dim_name in enumerate(var.dims):
        dim = schema.get_dimension(dim_name)
        if dim is None:
            continue
        expected_size = dim.size
        if partial_dims and dim_name in partial_dims:
            expected_size = partial_dims[dim_name]
        if expected_size is not None and arr.shape[i] != expected_size:
            raise ValueError(
                f"Variable '{variable_name}', dimension '{dim_name}': "
                f"data size {arr.shape[i]} != expected {expected_size}"
            )


def write_variable(
    zarr_path: str,
    variable_name: str,
    data: Any,
    *,
    schema: Optional[ZarrSchema] = None,
    slices: Optional[Dict[str, slice]] = None,
    validate: bool = True,
) -> int:
    """Write data to a variable in an existing zarr store.

    Args:
        zarr_path: Path to zarr store.
        variable_name: Variable to write to.
        data: Numpy array matching the variable shape (or slice thereof).
        schema: If provided, validate data against schema before writing.
        slices: Dict of {dim_name: slice} for partial writes. None = full write.
        validate: Whether to validate dtype/shape.

    Returns:
        Number of elements written.
    """
    import numpy as np
    import zarr

    from ._helpers import _open_zarr_store

    arr = np.asarray(data)

    if validate and schema is not None:
        _validate_data_for_variable(arr, variable_name, schema)

    root = _open_zarr_store(zarr_path, mode="r+")

    if variable_name not in root:
        raise KeyError(
            f"Variable '{variable_name}' not found in zarr store at {zarr_path}"
        )

    target = root[variable_name]

    if slices:
        # Build indexing tuple from dimension names
        dim_names = target.attrs.get("_ARRAY_DIMENSIONS", [])
        idx = []
        for i, dname in enumerate(dim_names):
            if dname in slices:
                idx.append(slices[dname])
            else:
                idx.append(slice(None))
        target[tuple(idx)] = arr
    else:
        target[:] = arr

    return int(arr.size)


def append_along_dimension(
    zarr_path: str,
    variable_name: str,
    data: Any,
    dimension: str,
    *,
    schema: Optional[ZarrSchema] = None,
    validate: bool = True,
    coordinate_values: Optional[Dict[str, Any]] = None,
) -> Tuple[int, int]:
    """Append data along an appendable dimension.

    Args:
        zarr_path: Path to zarr store.
        variable_name: Variable to append to.
        data: Array to append. All dims except `dimension` must match existing.
        dimension: Name of the dimension to append along.
        schema: If provided, validates the dimension is appendable.
        validate: Whether to run validation checks.
        coordinate_values: New values for coordinate arrays being extended.

    Returns:
        (old_size, new_size) for the appended dimension.
    """
    import numpy as np
    import zarr

    from ._helpers import _open_zarr_store

    arr = np.asarray(data)

    # Validate dimension is appendable
    if validate and schema is not None:
        dim = schema.get_dimension(dimension)
        if dim is None:
            raise ValueError(f"Dimension '{dimension}' not in schema")
        if dim.size is not None:
            raise ValueError(
                f"Dimension '{dimension}' has fixed size {dim.size}, cannot append"
            )

    root = _open_zarr_store(zarr_path, mode="r+")

    if variable_name not in root:
        raise KeyError(
            f"Variable '{variable_name}' not found in zarr store at {zarr_path}"
        )

    target = root[variable_name]
    dim_names = target.attrs.get("_ARRAY_DIMENSIONS", [])

    if dimension not in dim_names:
        raise ValueError(
            f"Dimension '{dimension}' not found in variable '{variable_name}'. "
            f"Available dimensions: {dim_names}"
        )

    dim_idx = dim_names.index(dimension)
    old_size = target.shape[dim_idx]
    append_size = arr.shape[dim_idx]
    new_size = old_size + append_size

    # Validate non-append dimensions match
    if validate:
        for i, dname in enumerate(dim_names):
            if i == dim_idx:
                continue
            if arr.shape[i] != target.shape[i]:
                raise ValueError(
                    f"Dimension '{dname}': data size {arr.shape[i]} != "
                    f"existing size {target.shape[i]}"
                )

    # Resize and write
    new_shape = list(target.shape)
    new_shape[dim_idx] = new_size
    target.resize(tuple(new_shape))

    # Build slice for the appended region
    idx = [slice(None)] * len(dim_names)
    idx[dim_idx] = slice(old_size, new_size)
    target[tuple(idx)] = arr

    # Update coordinate arrays if provided
    if coordinate_values:
        for coord_name, coord_data in coordinate_values.items():
            if coord_name in root:
                coord_arr = root[coord_name]
                coord_data = np.asarray(coord_data)
                coord_old = coord_arr.shape[0]
                coord_arr.resize(coord_old + len(coord_data))
                coord_arr[coord_old:] = coord_data

    return old_size, new_size


def write_store_attrs(
    zarr_path: str,
    attrs: Dict[str, Any],
    *,
    merge: bool = True,
) -> None:
    """Write or merge attributes into the zarr store root .zattrs.

    Args:
        zarr_path: Path to zarr store.
        attrs: Dict of attributes to write.
        merge: If True, merge with existing. If False, replace entirely.
    """
    from ._helpers import _open_zarr_store

    root = _open_zarr_store(zarr_path, mode="r+")

    if merge:
        existing = dict(root.attrs)
        existing.update(attrs)
        root.attrs.update(existing)
    else:
        root.attrs.clear()
        root.attrs.update(attrs)


def safe_write_variable(
    zarr_path: str,
    variable_name: str,
    data: Any,
    *,
    schema: Optional[ZarrSchema] = None,
) -> int:
    """Crash-safe write: copy store, write to copy, verify, swap.

    For critical writes where partial failure could corrupt the store.

    Args:
        zarr_path: Path to zarr store.
        variable_name: Variable to write.
        data: Data to write.
        schema: Optional schema for validation.

    Returns:
        Number of elements written.
    """
    import numpy as np

    store_path = Path(zarr_path)
    backup_path = store_path.with_name(store_path.name + ".backup")
    tmp_path = store_path.with_name(store_path.name + ".tmp_write")

    try:
        # Copy current store as backup
        if backup_path.exists():
            shutil.rmtree(backup_path)
        shutil.copytree(store_path, backup_path)

        # Copy to temp for writing
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        shutil.copytree(store_path, tmp_path)

        # Write to temp copy
        count = write_variable(
            str(tmp_path), variable_name, data, schema=schema, validate=True
        )

        # Verify the write
        from ._helpers import _open_zarr_store

        root = _open_zarr_store(str(tmp_path), mode="r")
        written = np.asarray(root[variable_name])
        expected = np.asarray(data)
        if written.shape != expected.shape:
            raise RuntimeError(
                f"Verification failed: shape {written.shape} != {expected.shape}"
            )

        # Swap: remove original, rename temp to original
        shutil.rmtree(store_path)
        tmp_path.rename(store_path)

        return count

    except Exception:
        # Restore from backup on any failure
        if backup_path.exists():
            if store_path.exists():
                shutil.rmtree(store_path)
            backup_path.rename(store_path)
        raise

    finally:
        # Clean up temp files
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        if backup_path.exists():
            shutil.rmtree(backup_path)


def consolidate(zarr_path: str) -> None:
    """Consolidate zarr metadata for efficient cloud access."""
    import zarr

    zarr.consolidate_metadata(zarr_path)
