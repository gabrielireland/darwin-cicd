#!/usr/bin/env python3
"""
Schema serialization: save/load ZarrSchema to/from JSON files.

Also provides schema_from_zarr() to reverse-engineer a schema from an
existing zarr store (lazy zarr import).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schema import (
    SCHEMA_VERSION,
    Compression,
    CoordinateSpec,
    Dimension,
    SpatialReference,
    VariableSpec,
    ZarrSchema,
)
from ._helpers import _atomic_write_json, _load_json_file


def schema_to_json(schema: ZarrSchema, indent: int = 2) -> str:
    """Serialize a ZarrSchema to a JSON string."""
    return json.dumps(schema.to_dict(), indent=indent, sort_keys=False, default=str)


def schema_from_json(text: str) -> ZarrSchema:
    """Deserialize a ZarrSchema from a JSON string."""
    data = json.loads(text)
    return ZarrSchema.from_dict(data)


def save_schema(schema: ZarrSchema, path: Path) -> None:
    """Atomically write schema to a JSON file."""
    errors = schema.validate()
    if errors:
        raise ValueError(f"Schema validation failed: {'; '.join(errors)}")
    _atomic_write_json(path, schema.to_dict())


def load_schema(path: Path) -> ZarrSchema:
    """Load schema from a JSON file. Validates schema_version."""
    data = _load_json_file(path)
    version = data.get("schema_version", 0)
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"Schema version mismatch: file has v{version}, "
            f"expected v{SCHEMA_VERSION}"
        )
    schema = ZarrSchema.from_dict(data)
    errors = schema.validate()
    if errors:
        raise ValueError(
            f"Loaded schema has validation errors: {'; '.join(errors)}"
        )
    return schema


def schema_from_zarr(zarr_path: str) -> ZarrSchema:
    """Reverse-engineer a ZarrSchema from an existing zarr store.

    Reads the zarr store metadata (array shapes, dtypes, chunks,
    compressor settings, .zattrs) and builds a schema that describes it.

    Args:
        zarr_path: Path to a local zarr store directory.

    Returns:
        A ZarrSchema describing the store's structure.
    """
    import zarr
    import numpy as np

    from ._helpers import _open_zarr_store

    root = _open_zarr_store(zarr_path, mode="r")
    attrs = dict(root.attrs)

    # Discover arrays (skip groups, skip .zattrs-only entries)
    array_names: List[str] = []
    for key in root:
        if isinstance(root[key], zarr.Array):
            array_names.append(key)

    # Build dimensions from the first variable's shape, or from coords
    dim_sizes: Dict[str, Optional[int]] = {}
    variables: List[VariableSpec] = []
    coordinates: List[CoordinateSpec] = []

    # Detect coordinate arrays: 1D arrays whose dimension name matches their
    # own name (e.g. array "feature" with _ARRAY_DIMENSIONS=["feature"])
    coord_names: set = set()

    for name in array_names:
        arr = root[name]
        if arr.ndim == 1:
            arr_attrs = dict(arr.attrs) if hasattr(arr, "attrs") else {}
            arr_dims = arr_attrs.get("_ARRAY_DIMENSIONS", [])
            if arr_dims and arr_dims[0] == name:
                coord_names.add(name)

    # Collect dimension info and build variable specs
    for name in array_names:
        arr = root[name]
        if name in coord_names:
            continue

        # Try to get dimension names from array attrs
        arr_attrs = dict(arr.attrs) if hasattr(arr, "attrs") else {}
        dim_names = arr_attrs.get("_ARRAY_DIMENSIONS", [])

        if not dim_names:
            # Generate generic dimension names
            dim_names = [f"dim_{i}" for i in range(arr.ndim)]

        for i, dname in enumerate(dim_names):
            if dname not in dim_sizes:
                dim_sizes[dname] = arr.shape[i]

        # Extract compression
        comp = None
        if arr.compressor is not None:
            c = arr.compressor
            codec = getattr(c, "cname", "zstd")
            level = getattr(c, "clevel", 5)
            shuffle = getattr(c, "shuffle", 2)
            comp = Compression(codec=codec, level=level, shuffle=shuffle)

        variables.append(VariableSpec(
            name=name,
            dims=tuple(dim_names),
            dtype=str(arr.dtype),
            chunks=tuple(arr.chunks) if arr.chunks else None,
            nodata=float(arr.fill_value) if arr.fill_value is not None and arr.fill_value != 0 else None,
            compression=comp,
        ))

    # Build coordinate specs from 1D arrays
    for name in coord_names:
        arr = root[name]
        arr_attrs = dict(arr.attrs) if hasattr(arr, "attrs") else {}
        dim_name = arr_attrs.get("_ARRAY_DIMENSIONS", [name])[0] if arr_attrs.get("_ARRAY_DIMENSIONS") else name

        if dim_name not in dim_sizes:
            dim_sizes[dim_name] = arr.shape[0]

        coordinates.append(CoordinateSpec(
            dimension=dim_name,
            dtype=str(arr.dtype),
            units=arr_attrs.get("units", ""),
        ))

    # Build Dimension objects
    dimensions = [
        Dimension(name=dname, size=dsize)
        for dname, dsize in dim_sizes.items()
    ]

    # Extract spatial reference from attrs
    spatial_ref = None
    epsg = attrs.get("epsg") or attrs.get("crs_epsg")
    wkt = attrs.get("crs_wkt", "")
    crs_str = attrs.get("crs", "")
    transform = attrs.get("transform")

    if epsg or wkt or crs_str:
        if not epsg and crs_str and crs_str.startswith("EPSG:"):
            try:
                epsg = int(crs_str.split(":")[1])
            except (IndexError, ValueError):
                pass
        spatial_ref = SpatialReference(
            epsg=epsg,
            wkt=wkt,
            transform=tuple(transform) if transform else None,
        )

    # Extract default compression from the first variable
    default_comp = Compression()
    if variables and variables[0].compression:
        default_comp = variables[0].compression

    return ZarrSchema(
        schema_version=SCHEMA_VERSION,
        name=Path(zarr_path).stem,
        description=f"Auto-generated from {zarr_path}",
        dimensions=dimensions,
        variables=variables,
        coordinates=coordinates,
        spatial_ref=spatial_ref,
        default_compression=default_comp,
        store_attrs={k: v for k, v in attrs.items()
                     if k not in ("crs", "crs_wkt", "crs_epsg", "epsg", "transform")},
    )
