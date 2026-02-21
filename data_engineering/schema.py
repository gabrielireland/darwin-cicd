#!/usr/bin/env python3
"""
Zarr schema definitions for geospatial data engineering.

Defines the structure of a zarr store: dimensions, variables, coordinates,
CRS, compression, and chunking. Project-agnostic — consumers define their
own schema via Python dicts or JSON config files.

Zero external dependencies (stdlib only).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Sub-dataclasses (frozen for immutability)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Dimension:
    """A named dimension in the zarr store.

    Args:
        name: Dimension name (e.g. "time", "band", "y", "x", "pixel").
        size: Fixed size, or None for appendable/unlimited dimensions.
        description: Human-readable description.
    """
    name: str
    size: Optional[int] = None
    description: str = ""


@dataclass(frozen=True)
class Compression:
    """Compression settings for a zarr array.

    Args:
        codec: Compressor name (zstd, lz4, zlib, snappy).
        level: Compression level (1-9).
        shuffle: Shuffle filter (0=none, 1=byte, 2=bitshuffle).
    """
    codec: str = "zstd"
    level: int = 5
    shuffle: int = 2


@dataclass(frozen=True)
class CoordinateSpec:
    """Coordinate variable definition (labels for a dimension).

    Args:
        dimension: Which dimension this coordinate labels.
        dtype: Numpy dtype string (e.g. "float64", "datetime64[ns]", "U20").
        units: Unit description (e.g. "meters", "degrees").
        description: Human-readable description.
    """
    dimension: str
    dtype: str = "float64"
    units: str = ""
    description: str = ""


@dataclass(frozen=True)
class VariableSpec:
    """A data variable in the zarr store.

    Args:
        name: Variable name (e.g. "embeddings", "labels", "reflectance").
        dims: Ordered dimension names as a tuple.
        dtype: Numpy dtype string.
        chunks: Per-dimension chunk sizes. None = auto. -1 = full dimension.
        nodata: Fill/nodata value. None means no explicit fill.
        compression: Per-variable override. None = use store default.
        description: Human-readable description.
        attrs: Extra zarr attributes on this variable.
    """
    name: str
    dims: Tuple[str, ...] = ()
    dtype: str = "float32"
    chunks: Optional[Tuple[int, ...]] = None
    nodata: Optional[Union[float, int]] = None
    compression: Optional[Compression] = None
    description: str = ""
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SpatialReference:
    """Geospatial CRS and transform metadata.

    Args:
        epsg: EPSG code (e.g. 4326, 32630). None if using WKT only.
        wkt: Well-Known Text string (fallback if no EPSG).
        transform: Affine as 6-tuple in GDAL order
                   (x_res, x_skew, x_origin, y_skew, y_res, y_origin).
        x_dim: Which dimension is easting/longitude.
        y_dim: Which dimension is northing/latitude.
        resolution: (x_res, y_res) in CRS units. Derived from transform if None.
    """
    epsg: Optional[int] = None
    wkt: str = ""
    transform: Optional[Tuple[float, ...]] = None
    x_dim: str = "x"
    y_dim: str = "y"
    resolution: Optional[Tuple[float, float]] = None


# ---------------------------------------------------------------------------
# Main schema class
# ---------------------------------------------------------------------------

@dataclass
class ZarrSchema:
    """Complete schema for a zarr store.

    Defines dimensions, variables, coordinates, spatial reference,
    and default compression. Serializable to/from JSON via to_dict()/from_dict().
    """
    schema_version: int = SCHEMA_VERSION
    name: str = ""
    description: str = ""

    dimensions: List[Dimension] = field(default_factory=list)
    variables: List[VariableSpec] = field(default_factory=list)
    coordinates: List[CoordinateSpec] = field(default_factory=list)
    spatial_ref: Optional[SpatialReference] = None

    default_compression: Compression = field(default_factory=Compression)
    consolidate_metadata: bool = True

    store_attrs: Dict[str, Any] = field(default_factory=dict)

    # -- query helpers --

    def dimension_names(self) -> List[str]:
        """Return ordered list of dimension names."""
        return [d.name for d in self.dimensions]

    def get_dimension(self, name: str) -> Optional[Dimension]:
        """Lookup a dimension by name."""
        for d in self.dimensions:
            if d.name == name:
                return d
        return None

    def get_variable(self, name: str) -> Optional[VariableSpec]:
        """Lookup a variable by name."""
        for v in self.variables:
            if v.name == name:
                return v
        return None

    def get_coordinate(self, dimension: str) -> Optional[CoordinateSpec]:
        """Lookup a coordinate by its dimension name."""
        for c in self.coordinates:
            if c.dimension == dimension:
                return c
        return None

    # -- validation --

    def validate(self) -> List[str]:
        """Validate schema internal consistency.

        Returns:
            List of error strings. Empty list means valid.
        """
        errors: List[str] = []
        dim_names = set(self.dimension_names())

        if not self.dimensions:
            errors.append("Schema has no dimensions defined")

        if not self.variables:
            errors.append("Schema has no variables defined")

        # Check dimension names are unique
        if len(dim_names) != len(self.dimensions):
            seen: set = set()
            for d in self.dimensions:
                if d.name in seen:
                    errors.append(f"Duplicate dimension name: '{d.name}'")
                seen.add(d.name)

        # Check variable names are unique
        var_names: set = set()
        for v in self.variables:
            if v.name in var_names:
                errors.append(f"Duplicate variable name: '{v.name}'")
            var_names.add(v.name)

        # Check variables reference valid dimensions
        for v in self.variables:
            for dim_name in v.dims:
                if dim_name not in dim_names:
                    errors.append(
                        f"Variable '{v.name}' references unknown dimension '{dim_name}'"
                    )

            # Check chunks length matches dims
            if v.chunks is not None and len(v.chunks) != len(v.dims):
                errors.append(
                    f"Variable '{v.name}': chunks length ({len(v.chunks)}) "
                    f"!= dims length ({len(v.dims)})"
                )

        # Check coordinates reference valid dimensions
        for c in self.coordinates:
            if c.dimension not in dim_names:
                errors.append(
                    f"Coordinate references unknown dimension '{c.dimension}'"
                )

        # Check spatial reference dimension names (only if dims exist in schema)
        if self.spatial_ref is not None:
            if (self.spatial_ref.x_dim
                    and self.spatial_ref.x_dim in dim_names
                    and self.spatial_ref.y_dim
                    and self.spatial_ref.y_dim not in dim_names):
                errors.append(
                    f"SpatialReference y_dim '{self.spatial_ref.y_dim}' "
                    f"not in dimensions"
                )
            if (self.spatial_ref.y_dim
                    and self.spatial_ref.y_dim in dim_names
                    and self.spatial_ref.x_dim
                    and self.spatial_ref.x_dim not in dim_names):
                errors.append(
                    f"SpatialReference x_dim '{self.spatial_ref.x_dim}' "
                    f"not in dimensions"
                )
            if self.spatial_ref.epsg is None and not self.spatial_ref.wkt:
                errors.append("SpatialReference has neither epsg nor wkt set")

        return errors

    # -- serialization --

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict (JSON-safe).

        Tuples are converted to lists for JSON compatibility.
        """
        raw = asdict(self)
        # Remove None spatial_ref to keep output clean
        if raw.get("spatial_ref") is None:
            del raw["spatial_ref"]
        return raw

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ZarrSchema:
        """Deserialize from a plain dict (e.g. parsed JSON).

        Handles list-to-tuple conversions for frozen dataclass fields.
        """
        d = dict(data)

        d["dimensions"] = [
            Dimension(**dim) for dim in d.get("dimensions", [])
        ]

        variables = []
        for v in d.get("variables", []):
            v = dict(v)
            if v.get("dims") is not None:
                v["dims"] = tuple(v["dims"])
            if v.get("chunks") is not None:
                v["chunks"] = tuple(v["chunks"])
            if v.get("compression") is not None:
                v["compression"] = Compression(**v["compression"])
            if "attrs" not in v:
                v["attrs"] = {}
            variables.append(VariableSpec(**v))
        d["variables"] = variables

        d["coordinates"] = [
            CoordinateSpec(**c) for c in d.get("coordinates", [])
        ]

        sr = d.get("spatial_ref")
        if sr is not None:
            sr = dict(sr)
            if sr.get("transform") is not None:
                sr["transform"] = tuple(sr["transform"])
            if sr.get("resolution") is not None:
                sr["resolution"] = tuple(sr["resolution"])
            d["spatial_ref"] = SpatialReference(**sr)

        dc = d.get("default_compression")
        if dc is not None:
            d["default_compression"] = Compression(**dc)

        if "store_attrs" not in d:
            d["store_attrs"] = {}

        return cls(**d)
