#!/usr/bin/env python3
"""
Zarr data engineering CLI.

Subcommands:
    create      Create an empty zarr store from a schema JSON file
    write       Write data from a .npy file into a zarr variable
    append      Append data along a dimension
    validate    Validate a zarr store against a schema
    inspect     Print zarr metadata as JSON
    schema      Generate a schema JSON from an existing zarr store

Usage:
    python3 cicd/data_engineering/zarr_cli.py create \
        --schema schema.json --output features.zarr --overwrite

    python3 cicd/data_engineering/zarr_cli.py validate \
        --schema schema.json --zarr features.zarr --strict
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _cmd_create(args: argparse.Namespace) -> int:
    """Create zarr store from schema."""
    from .schema_io import load_schema
    from .zarr_create import create_zarr_store
    from ._helpers import _load_json_file

    schema = load_schema(Path(args.schema))

    # Load coordinate values if provided
    coord_values: Optional[Dict[str, Any]] = None
    if args.coords_json:
        import numpy as np

        raw = _load_json_file(Path(args.coords_json))
        coord_values = {k: np.array(v) for k, v in raw.items()}

    # Apply --var overrides to store_attrs
    if args.var:
        for kv in args.var:
            key, _, value = kv.partition("=")
            if not key:
                print(f"ERROR: Invalid --var format: '{kv}' (use KEY=VALUE)", file=sys.stderr)
                return 1
            schema.store_attrs[key] = value

    path = create_zarr_store(
        schema, args.output,
        coordinate_values=coord_values,
        overwrite=args.overwrite,
        use_xarray=args.use_xarray,
    )
    print(f"Created zarr store: {path}")
    return 0


def _cmd_write(args: argparse.Namespace) -> int:
    """Write .npy data into a zarr variable."""
    import numpy as np

    data = np.load(args.data)

    schema = None
    if args.schema:
        from .schema_io import load_schema
        schema = load_schema(Path(args.schema))

    slices = None
    if args.slices:
        raw_slices = json.loads(args.slices)
        slices = {k: slice(*v) for k, v in raw_slices.items()}

    if args.safe:
        from .zarr_write import safe_write_variable
        count = safe_write_variable(args.zarr, args.variable, data, schema=schema)
    else:
        from .zarr_write import write_variable
        count = write_variable(
            args.zarr, args.variable, data, schema=schema, slices=slices
        )

    print(f"Wrote {count} elements to {args.variable}")
    return 0


def _cmd_append(args: argparse.Namespace) -> int:
    """Append .npy data along a dimension."""
    import numpy as np

    from .zarr_write import append_along_dimension

    data = np.load(args.data)

    schema = None
    if args.schema:
        from .schema_io import load_schema
        schema = load_schema(Path(args.schema))

    coord_values = None
    if args.coords_json:
        from ._helpers import _load_json_file
        raw = _load_json_file(Path(args.coords_json))
        coord_values = {k: np.array(v) for k, v in raw.items()}

    old_size, new_size = append_along_dimension(
        args.zarr, args.variable, data, args.dimension,
        schema=schema, coordinate_values=coord_values,
    )
    print(f"Appended along '{args.dimension}': {old_size} -> {new_size}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate zarr against schema. Exit 0=valid, 2=invalid (if --strict)."""
    from .schema_io import load_schema
    from .zarr_validate import validate_zarr

    schema = load_schema(Path(args.schema))
    result = validate_zarr(args.zarr, schema, strict=args.strict)

    if args.output_json:
        from ._helpers import _atomic_write_json
        _atomic_write_json(Path(args.output_json), result.to_dict())
        print(f"Validation result written to {args.output_json}")

    print(result.summary())

    if not result.valid:
        return 2
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    """Print zarr store info as JSON."""
    import zarr

    from ._helpers import _open_zarr_store

    root = _open_zarr_store(args.zarr, mode="r")

    info: Dict[str, Any] = {
        "path": args.zarr,
        "attrs": dict(root.attrs),
        "arrays": {},
    }

    for key in root:
        if isinstance(root[key], zarr.Array):
            arr = root[key]
            info["arrays"][key] = {
                "shape": list(arr.shape),
                "dtype": str(arr.dtype),
                "chunks": list(arr.chunks) if arr.chunks else None,
                "fill_value": arr.fill_value if arr.fill_value is not None else None,
                "compressor": str(getattr(arr, "compressors", None) or getattr(arr, "compressor", None)),
                "dims": arr.attrs.get("_ARRAY_DIMENSIONS", []),
                "attrs": {k: v for k, v in arr.attrs.items()
                          if k != "_ARRAY_DIMENSIONS"},
            }

    output = json.dumps(info, indent=2, default=str)

    if args.output_json:
        Path(args.output_json).write_text(output + "\n", encoding="utf-8")
        print(f"Inspection written to {args.output_json}")
    else:
        print(output)

    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    """Generate schema JSON from existing zarr."""
    from .schema_io import schema_from_zarr, save_schema

    schema = schema_from_zarr(args.zarr)
    if args.name:
        schema.name = args.name

    save_schema(schema, Path(args.output))
    print(f"Schema written to {args.output}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zarr_cli",
        description="Zarr data engineering CLI (project-agnostic)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p = sub.add_parser("create", help="Create empty zarr from schema")
    p.add_argument("--schema", required=True, help="Path to schema JSON")
    p.add_argument("--output", required=True, help="Output zarr path")
    p.add_argument("--coords-json", help="JSON with coordinate values {name: [values]}")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--use-xarray", action="store_true",
                    help="Use xarray for CF conventions + rioxarray CRS")
    p.add_argument("--var", action="append",
                    help="Override store_attrs KEY=VALUE (repeatable)")
    p.set_defaults(func=_cmd_create)

    # write
    p = sub.add_parser("write", help="Write .npy data to a zarr variable")
    p.add_argument("--zarr", required=True, help="Path to zarr store")
    p.add_argument("--variable", required=True, help="Variable name")
    p.add_argument("--data", required=True, help="Path to .npy file")
    p.add_argument("--schema", help="Schema JSON for validation")
    p.add_argument("--slices", help="JSON dict of dim slices, e.g. '{\"band\": [0, 10]}'")
    p.add_argument("--safe", action="store_true", help="Use crash-safe backup write")
    p.set_defaults(func=_cmd_write)

    # append
    p = sub.add_parser("append", help="Append data along a dimension")
    p.add_argument("--zarr", required=True)
    p.add_argument("--variable", required=True)
    p.add_argument("--data", required=True, help="Path to .npy file")
    p.add_argument("--dimension", required=True, help="Dimension to append along")
    p.add_argument("--schema", help="Schema JSON for validation")
    p.add_argument("--coords-json", help="JSON with new coordinate values")
    p.set_defaults(func=_cmd_append)

    # validate
    p = sub.add_parser("validate", help="Validate zarr against schema")
    p.add_argument("--zarr", required=True)
    p.add_argument("--schema", required=True)
    p.add_argument("--strict", action="store_true",
                    help="Exit 2 on any issue (warnings become errors)")
    p.add_argument("--output-json", help="Write result to JSON file")
    p.set_defaults(func=_cmd_validate)

    # inspect
    p = sub.add_parser("inspect", help="Print zarr metadata as JSON")
    p.add_argument("--zarr", required=True)
    p.add_argument("--output-json", help="Write to file instead of stdout")
    p.set_defaults(func=_cmd_inspect)

    # schema (reverse-engineer)
    p = sub.add_parser("schema", help="Generate schema from existing zarr")
    p.add_argument("--zarr", required=True)
    p.add_argument("--output", required=True, help="Output schema JSON path")
    p.add_argument("--name", default="", help="Schema name")
    p.set_defaults(func=_cmd_schema)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, KeyError, FileExistsError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
