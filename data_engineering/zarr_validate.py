#!/usr/bin/env python3
"""
Validate zarr stores against schema definitions.

Checks: dimensions, variable shapes, dtypes, chunking, CRS, coordinates,
compression, nodata values. Returns structured ValidationResult.

All heavy imports are lazy (inside functions).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .schema import ZarrSchema


@dataclass
class ValidationIssue:
    """A single validation finding."""
    severity: str          # "error" | "warning"
    category: str          # "dimension", "variable", "coordinate", "crs", "compression", "attrs"
    message: str = ""
    variable: str = ""
    expected: str = ""
    actual: str = ""

    def __str__(self) -> str:
        parts = [f"[{self.severity.upper()}] {self.category}"]
        if self.variable:
            parts.append(f"({self.variable})")
        parts.append(f": {self.message}")
        if self.expected or self.actual:
            parts.append(f" (expected={self.expected}, actual={self.actual})")
        return "".join(parts)


@dataclass
class ValidationResult:
    """Complete validation result."""
    valid: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def _add(self, severity: str, category: str, message: str, **kwargs: Any) -> None:
        self.issues.append(ValidationIssue(
            severity=severity, category=category, message=message, **kwargs
        ))
        if severity == "error":
            self.valid = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "variable": i.variable,
                    "message": i.message,
                    "expected": i.expected,
                    "actual": i.actual,
                }
                for i in self.issues
            ],
        }

    def summary(self) -> str:
        if self.valid and not self.warnings:
            return "OK: zarr store matches schema"
        lines = []
        if self.errors:
            lines.append(f"{len(self.errors)} error(s)")
        if self.warnings:
            lines.append(f"{len(self.warnings)} warning(s)")
        header = "INVALID: " if not self.valid else "VALID with warnings: "
        header += ", ".join(lines)
        for issue in self.issues:
            header += f"\n  {issue}"
        return header


def validate_zarr(
    zarr_path: str,
    schema: ZarrSchema,
    *,
    check_chunks: bool = True,
    check_compression: bool = True,
    check_coordinates: bool = True,
    check_crs: bool = True,
    check_nodata: bool = True,
    strict: bool = False,
) -> ValidationResult:
    """Validate a zarr store against a schema.

    Args:
        zarr_path: Path to the zarr store.
        schema: Schema to validate against.
        check_chunks: Verify chunk sizes match.
        check_compression: Verify compression settings.
        check_coordinates: Verify coordinate arrays.
        check_crs: Verify CRS/transform metadata.
        check_nodata: Verify fill values.
        strict: If True, warnings become errors.

    Returns:
        ValidationResult with all findings.
    """
    import numpy as np

    from ._helpers import _open_zarr_store

    result = ValidationResult()
    sev_warn = "error" if strict else "warning"

    try:
        root = _open_zarr_store(zarr_path, mode="r")
    except Exception as exc:
        result._add("error", "store", f"Cannot open zarr store: {exc}")
        return result

    attrs = dict(root.attrs)

    # -- Check variables exist with correct shape/dtype --
    for var in schema.variables:
        if var.name not in root:
            result._add("error", "variable", f"Missing variable '{var.name}'",
                         variable=var.name)
            continue

        arr = root[var.name]

        # Dtype
        expected_dtype = np.dtype(var.dtype)
        if arr.dtype != expected_dtype:
            result._add("error", "variable", "dtype mismatch",
                         variable=var.name,
                         expected=str(expected_dtype), actual=str(arr.dtype))

        # Ndim
        if arr.ndim != len(var.dims):
            result._add("error", "variable",
                         f"ndim {arr.ndim} != expected {len(var.dims)}",
                         variable=var.name)
            continue

        # Shape (only fixed-size dimensions)
        for i, dim_name in enumerate(var.dims):
            dim = schema.get_dimension(dim_name)
            if dim and dim.size is not None and arr.shape[i] != dim.size:
                result._add("error", "dimension",
                             f"size mismatch for '{dim_name}'",
                             variable=var.name,
                             expected=str(dim.size), actual=str(arr.shape[i]))

        # Chunks
        if check_chunks and var.chunks is not None and arr.chunks:
            from .zarr_create import _resolve_chunks
            expected_chunks = _resolve_chunks(var, schema)
            if expected_chunks and tuple(arr.chunks) != expected_chunks:
                result._add(sev_warn, "compression",
                             "chunk size mismatch",
                             variable=var.name,
                             expected=str(expected_chunks),
                             actual=str(arr.chunks))

        # Compression
        if check_compression and arr.compressor is not None:
            comp = var.compression or schema.default_compression
            actual_codec = getattr(arr.compressor, "cname", "")
            if actual_codec != comp.codec:
                result._add(sev_warn, "compression",
                             "codec mismatch",
                             variable=var.name,
                             expected=comp.codec, actual=actual_codec)

        # Nodata / fill_value
        if check_nodata and var.nodata is not None:
            if arr.fill_value != var.nodata:
                # Handle NaN comparison
                is_nan_match = (
                    isinstance(var.nodata, float) and np.isnan(var.nodata)
                    and isinstance(arr.fill_value, float) and np.isnan(arr.fill_value)
                )
                if not is_nan_match:
                    result._add(sev_warn, "variable",
                                 "nodata/fill_value mismatch",
                                 variable=var.name,
                                 expected=str(var.nodata),
                                 actual=str(arr.fill_value))

        # Dimension name metadata
        arr_dims = arr.attrs.get("_ARRAY_DIMENSIONS", [])
        if arr_dims and tuple(arr_dims) != var.dims:
            result._add("error", "variable",
                         "dimension names mismatch",
                         variable=var.name,
                         expected=str(var.dims), actual=str(arr_dims))

    # -- Check coordinates --
    if check_coordinates:
        for coord in schema.coordinates:
            if coord.dimension not in root:
                result._add(sev_warn, "coordinate",
                             f"Missing coordinate array '{coord.dimension}'")
                continue

            arr = root[coord.dimension]
            expected_dtype = np.dtype(coord.dtype)
            if arr.dtype != expected_dtype:
                result._add(sev_warn, "coordinate",
                             f"dtype mismatch for '{coord.dimension}'",
                             expected=str(expected_dtype),
                             actual=str(arr.dtype))

            dim = schema.get_dimension(coord.dimension)
            if dim and dim.size is not None and arr.shape[0] != dim.size:
                result._add("error", "coordinate",
                             f"size mismatch for '{coord.dimension}'",
                             expected=str(dim.size),
                             actual=str(arr.shape[0]))

    # -- Check CRS --
    if check_crs and schema.spatial_ref:
        sr = schema.spatial_ref
        if sr.epsg:
            store_crs = attrs.get("crs", "")
            store_epsg = attrs.get("crs_epsg")
            expected_crs = f"EPSG:{sr.epsg}"
            if store_epsg and store_epsg != sr.epsg:
                result._add("error", "crs", "EPSG code mismatch",
                             expected=str(sr.epsg), actual=str(store_epsg))
            elif store_crs and store_crs != expected_crs:
                result._add("error", "crs", "CRS string mismatch",
                             expected=expected_crs, actual=store_crs)
            elif not store_crs and not store_epsg:
                result._add("error", "crs", "No CRS metadata found in store")

        if sr.transform:
            store_transform = attrs.get("transform")
            if store_transform:
                if tuple(store_transform) != tuple(sr.transform):
                    result._add("error", "crs", "Transform mismatch",
                                 expected=str(sr.transform),
                                 actual=str(store_transform))
            else:
                result._add(sev_warn, "crs", "No transform metadata in store")

    return result


def validate_data_against_schema(
    data: Any,
    variable_name: str,
    schema: ZarrSchema,
) -> ValidationResult:
    """Validate an in-memory array against a variable's schema spec.

    Useful for pre-write validation to catch issues before touching the store.
    """
    import numpy as np

    result = ValidationResult()

    var = schema.get_variable(variable_name)
    if var is None:
        result._add("error", "variable",
                     f"Variable '{variable_name}' not found in schema")
        return result

    arr = np.asarray(data)

    expected_dtype = np.dtype(var.dtype)
    if arr.dtype != expected_dtype:
        if np.can_cast(arr.dtype, expected_dtype, casting="safe"):
            result._add("warning", "variable",
                         "dtype will be cast",
                         variable=variable_name,
                         expected=str(expected_dtype), actual=str(arr.dtype))
        else:
            result._add("error", "variable",
                         "dtype cannot be safely cast",
                         variable=variable_name,
                         expected=str(expected_dtype), actual=str(arr.dtype))

    if arr.ndim != len(var.dims):
        result._add("error", "variable",
                     f"ndim {arr.ndim} != expected {len(var.dims)}",
                     variable=variable_name)
        return result

    for i, dim_name in enumerate(var.dims):
        dim = schema.get_dimension(dim_name)
        if dim and dim.size is not None and arr.shape[i] != dim.size:
            result._add("error", "dimension",
                         f"size mismatch for '{dim_name}'",
                         variable=variable_name,
                         expected=str(dim.size), actual=str(arr.shape[i]))

    return result
