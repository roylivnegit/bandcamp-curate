#!/usr/bin/env python3
"""Turn a TOML output contract into a JSON Schema for `claude -p --json-schema`.

The contract format is deliberately small — see team/schema/*.toml:

    [meta]
    name = "turn"
    description = "..."

    [[field]]
    name = "stance"
    type = "enum"
    values = ["support", "object"]
    required = true
    help = "shown to the model as the field description"

Types: string, text, int, number, bool, enum, string[], enum[], object[].
`object[]` takes `schema = "<other contract name>"` and is resolved from the same directory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import tomllib

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"

_SCALARS = {
    "string": {"type": "string"},
    "text": {"type": "string"},
    "int": {"type": "integer"},
    "number": {"type": "number"},
    "bool": {"type": "boolean"},
}


def _field_schema(field: dict, seen: tuple[str, ...]) -> dict:
    ftype = field.get("type", "string")

    if ftype in _SCALARS:
        node = dict(_SCALARS[ftype])
    elif ftype == "enum":
        node = {"type": "string", "enum": list(field["values"])}
    elif ftype == "string[]":
        node = {"type": "array", "items": {"type": "string"}}
    elif ftype == "enum[]":
        node = {"type": "array", "items": {"type": "string", "enum": list(field["values"])}}
    elif ftype == "object[]":
        node = {"type": "array", "items": build(field["schema"], seen)}
    else:
        raise ValueError(f"unknown field type {ftype!r} on field {field.get('name')!r}")

    if help_text := field.get("help"):
        node["description"] = help_text
    if ftype.endswith("[]"):
        if (lo := field.get("min")) is not None:
            node["minItems"] = lo
        if (hi := field.get("max")) is not None:
            node["maxItems"] = hi
    return node


def build(name: str, seen: tuple[str, ...] = ()) -> dict:
    """Build the JSON Schema for the contract called `name`."""
    if name in seen:
        raise ValueError(f"circular contract reference: {' -> '.join((*seen, name))}")

    path = SCHEMA_DIR / f"{name}.toml"
    if not path.is_file():
        raise FileNotFoundError(f"no contract named {name!r} in {SCHEMA_DIR}")

    doc = tomllib.loads(path.read_text())
    fields = doc.get("field", [])
    if not fields:
        raise ValueError(f"contract {name!r} declares no [[field]] entries")

    properties: dict[str, dict] = {}
    required: list[str] = []
    for field in fields:
        key = field["name"]
        properties[key] = _field_schema(field, (*seen, name))
        if field.get("required"):
            required.append(key)

    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    if description := doc.get("meta", {}).get("description"):
        schema["description"] = description
    return schema


def main(argv: list[str]) -> int:
    if not argv:
        names = sorted(p.stem for p in SCHEMA_DIR.glob("*.toml"))
        print("contracts:", ", ".join(names), file=sys.stderr)
        return 2

    for arg in argv:
        print(json.dumps(build(Path(arg).stem), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
