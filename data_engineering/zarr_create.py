#!/usr/bin/env python3
"""
Create empty zarr stores from schema definitions.

Two modes:
  - Raw zarr (default): uses zarr + numcodecs only. Writes CRS to .zattrs.
  - xarray mode: uses xarray + rioxarray for CF-convention metadata.

All heavy imports are lazy (inside functions).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from .schema import Compression, VariableSpec, ZarrSchema


def _compression_to_numcodecs(comp: Compression) -> Any:
    """Convert schema Compression to a numcodecs compressor instance."""
    from numcodecs import Blosc

    shuffle_map = {
        0: Blosc.NOSHUFFLE,
        1: Blosc.SHUFFLE,
        2: Blosc.BITSHUFFLE,
    }
    return Blosc(
        cname=comp.codec,
        clevel=comp.level,
        shuffle=shuffle_map.get(comp.shuffle, Blosc.BITSHUFFLE),
    )


def _resolve_chunks(
    var: VariableSpec, schema: ZarrSchema
) -> tuple:
    """Resolve chunk sizes, replacing -1 with full dimension size."""
    if var.chunks is None:
        return None

    import numpy as np

    resolved = []
    for i, c in enumerate(var.chunks):
        if c == -1:
            dim = schema.get_dimension(var.dims[i])
            if dim and dim.size:
                resolved.append(dim.size)
            else:
                resolved.append(1)
        else:
            resolved.append(c)
    return tuple(resolved)


def _build_shape(var: VariableSpec, schema: ZarrSchema) -> tuple:
    """Build the initial shape for a variable, using 0 for appendable dims."""
    shape = []
    for dim_name in var.dims:
        dim = schema.get_dimension(dim_name)
        if dim is None:
            raise ValueError(
                f"Variable '{var.name}' references unknown dimension '{dim_name}'"
            )
        shape.append(dim.size if dim.size is not None else 0)
    return tuple(shape)


def _create_raw_zarr(
    schema: ZarrSchema,
    path: str,
    coordinate_values: Optional[Dict[str, Any]],
) -> None:
    """Create zarr store using raw zarr API (no xarray dependency)."""
    import zarr
    import numpy as np

    root = zarr.open(path, mode="w", zarr_format=2)

    default_compressor = _compression_to_numcodecs(schema.default_compression)

    # Create data variables
    for var in schema.variables:
        shape = _build_shape(var, schema)
        chunks = _resolve_chunks(var, schema)
        compressor = (
            _compression_to_numcodecs(var.compression)
            if var.compression
            else default_compressor
        )

        # Determine fill value
        fill_value: Any = 0
        if var.nodata is not None:
            fill_value = var.nodata
        elif "float" in var.dtype:
            fill_value = float("nan")

        arr = root.create_array(
            name=var.name,
            shape=shape,
            chunks=chunks,
            dtype=np.dtype(var.dtype),
            compressor=compressor,
            fill_value=fill_value,
            overwrite=True,
        )

        # Store dimension names (xarray convention for interop)
        arr.attrs["_ARRAY_DIMENSIONS"] = list(var.dims)

        if var.description:
            arr.attrs["description"] = var.description
        for k, v in var.attrs.items():
            arr.attrs[k] = v

    # Create coordinate arrays
    coord_values = coordinate_values or {}
    for coord in schema.coordinates:
        values = coord_values.get(coord.dimension)
        dim = schema.get_dimension(coord.dimension)

        if values is not None:
            arr = root.create_array(
                name=coord.dimension,
                data=np.asarray(values, dtype=np.dtype(coord.dtype)),
                chunks=(len(values),),
                overwrite=True,
            )
        elif dim and dim.size:
            arr = root.create_array(
                name=coord.dimension,
                shape=(dim.size,),
                dtype=np.dtype(coord.dtype),
                chunks=(dim.size,),
                overwrite=True,
            )
        else:
            arr = root.create_array(
                name=coord.dimension,
                shape=(0,),
                dtype=np.dtype(coord.dtype),
                chunks=(1,),
                overwrite=True,
            )

        arr.attrs["_ARRAY_DIMENSIONS"] = [coord.dimension]
        if coord.units:
            arr.attrs["units"] = coord.units
        if coord.description:
            arr.attrs["description"] = coord.description

    # Write store-level attributes
    root.attrs["schema_version"] = schema.schema_version
    if schema.name:
        root.attrs["schema_name"] = schema.name

    # Spatial reference
    if schema.spatial_ref:
        sr = schema.spatial_ref
        if sr.epsg:
            root.attrs["crs"] = f"EPSG:{sr.epsg}"
            root.attrs["crs_epsg"] = sr.epsg
        if sr.wkt:
            root.attrs["crs_wkt"] = sr.wkt
        if sr.transform:
            root.attrs["transform"] = list(sr.transform)
        if sr.resolution:
            root.attrs["resolution"] = list(sr.resolution)

    # Custom store attrs
    for k, v in schema.store_attrs.items():
        root.attrs[k] = v

    # Consolidate metadata for efficient cloud access
    if schema.consolidate_metadata:
        zarr.consolidate_metadata(path)


def _create_xarray_zarr(
    schema: ZarrSchema,
    path: str,
    coordinate_values: Optional[Dict[str, Any]],
) -> None:
    """Create zarr store using xarray.Dataset (CF conventions, rioxarray CRS)."""
    import numpy as np
    import xarray as xr

    coord_values = coordinate_values or {}
    coords: Dict[str, Any] = {}

    # Build coordinate arrays
    for coord in schema.coordinates:
        values = coord_values.get(coord.dimension)
        dim = schema.get_dimension(coord.dimension)
        if values is not None:
            coords[coord.dimension] = np.asarray(values, dtype=np.dtype(coord.dtype))
        elif dim and dim.size:
            coords[coord.dimension] = np.zeros(dim.size, dtype=np.dtype(coord.dtype))

    # Build data variables
    data_vars: Dict[str, Any] = {}
    encoding: Dict[str, Any] = {}

    default_compressor = _compression_to_numcodecs(schema.default_compression)

    for var in schema.variables:
        shape = _build_shape(var, schema)
        fill = var.nodata if var.nodata is not None else (
            float("nan") if "float" in var.dtype else 0
        )
        data = np.full(shape, fill, dtype=np.dtype(var.dtype))
        data_vars[var.name] = (list(var.dims), data)

        chunks = _resolve_chunks(var, schema)
        compressor = (
            _compression_to_numcodecs(var.compression)
            if var.compression
            else default_compressor
        )
        enc: Dict[str, Any] = {"compressor": compressor}
        if chunks:
            enc["chunks"] = chunks
        encoding[var.name] = enc

    ds = xr.Dataset(data_vars=data_vars, coords=coords, attrs=dict(schema.store_attrs))

    # Write CRS via rioxarray
    if schema.spatial_ref:
        import rioxarray  # noqa: F401 — registers .rio accessor

        sr = schema.spatial_ref
        if sr.epsg:
            ds = ds.rio.write_crs(f"EPSG:{sr.epsg}")
        elif sr.wkt:
            ds = ds.rio.write_crs(sr.wkt)
        if sr.transform:
            ds = ds.rio.write_transform()

    ds.to_zarr(path, mode="w", encoding=encoding, consolidated=schema.consolidate_metadata)


def create_zarr_store(
    schema: ZarrSchema,
    path: str,
    *,
    coordinate_values: Optional[Dict[str, Any]] = None,
    overwrite: bool = False,
    use_xarray: bool = False,
) -> str:
    """Create an empty zarr store conforming to the given schema.

    Args:
        schema: The zarr schema definition.
        path: Local path for the zarr store directory.
        coordinate_values: Dict mapping coordinate dimension name to array of values.
        overwrite: If True, remove existing store first.
        use_xarray: If True, create via xarray.Dataset with CF conventions
                    and rioxarray CRS. If False, use raw zarr (lighter).

    Returns:
        The path to the created zarr store.

    Raises:
        ValueError: If schema validation fails.
        FileExistsError: If store exists and overwrite is False.
    """
    errors = schema.validate()
    if errors:
        raise ValueError(f"Schema validation failed: {'; '.join(errors)}")

    store_path = Path(path)
    if store_path.exists():
        if overwrite:
            shutil.rmtree(store_path)
        else:
            raise FileExistsError(
                f"Zarr store already exists at {path}. Use overwrite=True to replace."
            )

    if use_xarray:
        _create_xarray_zarr(schema, path, coordinate_values)
    else:
        _create_raw_zarr(schema, path, coordinate_values)

    return path
