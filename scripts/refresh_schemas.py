#!/usr/bin/env python3
"""Regenerate free_plugin_blender/data/schemas/ from fal.ai for every catalog model.

Run after editing data/models.json. Works without Blender: the provider
modules are loaded under a stand-in package so the add-on's bpy imports never run.
"""

import json
import sys
import types
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "free_plugin_blender"

for name, path in (("fpb", PKG), ("fpb.providers", PKG / "providers")):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module

from fpb.providers import fal_schema  # noqa: E402


def main() -> int:
    catalog = json.loads((PKG / "data" / "models.json").read_text())
    entries = [e for slot in ("image", "video", "mesh") for e in catalog.get(slot, [])]
    ids = sorted({e[k] for e in entries for k in ("text", "image") if k in e})
    out = PKG / "data" / "schemas"
    out.mkdir(parents=True, exist_ok=True)
    failures = 0
    for endpoint_id in ids:
        try:
            schema = fal_schema.fetch(endpoint_id)
        except Exception as error:  # noqa: BLE001
            print(f"FAIL {endpoint_id}: {error}")
            failures += 1
            continue
        (out / fal_schema.safe_name(endpoint_id)).write_text(json.dumps(schema, indent=1) + "\n")
        print(f"ok   {endpoint_id}: {len(schema['fields'])} options, image field {schema['image_field']}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
