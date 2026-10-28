#!/usr/bin/env python3
"""Regenerate free_plugin_blender/data/animations.json from Meshy's animation library.

The presets are applied on fal.ai (fal-ai/meshy/rigging, animation_action_id), so the
add-on needs no Meshy key at runtime; this maintainer script does (free call):
    MESHY_API_KEY=... python3 scripts/refresh_animations.py
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "free_plugin_blender" / "data" / "animations.json"
URL = "https://api.meshy.ai/openapi/v1/animations/library"


def main() -> int:
    key = os.environ.get("MESHY_API_KEY", "").strip()
    if not key:
        print("Set MESHY_API_KEY")
        return 1
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "free-plugin-blender"}
    request = urllib.request.Request(URL, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    items = data if isinstance(data, list) else data.get("result") or data.get("animations") or data.get("data") or []
    presets = []
    for item in items:
        key_name = item.get("key") or item.get("action_key") or ""
        presets.append({
            "id": item.get("action_id", item.get("id")),
            "name": (item.get("name") or key_name).strip(),
            "category": item.get("category", ""),
            "sub": item.get("sub_category", ""),
            "in_place": key_name.endswith("_inplace"),
        })
    presets = [p for p in presets if isinstance(p["id"], int)]
    presets.sort(key=lambda p: (p["category"], p["sub"], p["name"].lower(), p["in_place"]))
    OUT.write_text(json.dumps({"_source": URL, "presets": presets}, indent=0, ensure_ascii=False) + "\n")
    print(f"{len(presets)} presets → {OUT.relative_to(OUT.parents[2])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
