"""
Reusable geospatial zarr data engineering tooling.

Schema layer (stdlib only — no zarr/numpy required):
    ZarrSchema, Dimension, VariableSpec, CoordinateSpec,
    SpatialReference, Compression
    load_schema, save_schema, schema_from_zarr

Zarr operations (requires zarr, numpy, numcodecs):
    create_zarr_store
    write_variable, append_along_dimension, safe_write_variable, consolidate
    validate_zarr, validate_data_against_schema, ValidationResult
"""
from .schema import (
    SCHEMA_VERSION,
    Compression,
    CoordinateSpec,
    Dimension,
    SpatialReference,
    VariableSpec,
    ZarrSchema,
)
from .schema_io import (
    load_schema,
    save_schema,
    schema_from_json,
    schema_from_zarr,
    schema_to_json,
)

# Zarr operations are imported lazily by consumers:
#   from cicd.data_engineering.zarr_create import create_zarr_store
#   from cicd.data_engineering.zarr_write import write_variable, ...
#   from cicd.data_engineering.zarr_validate import validate_zarr, ...

__all__ = [
    "SCHEMA_VERSION",
    "Compression",
    "CoordinateSpec",
    "Dimension",
    "SpatialReference",
    "VariableSpec",
    "ZarrSchema",
    "load_schema",
    "save_schema",
    "schema_from_json",
    "schema_from_zarr",
    "schema_to_json",
]
