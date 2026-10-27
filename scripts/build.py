#!/usr/bin/env python3
"""Zip `free_plugin_blender/` into `dist/free_plugin_blender-<version>.zip`.

Same result as `blender --command extension build --source-dir free_plugin_blender`,
without needing Blender (used by CI).
"""

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "free_plugin_blender"


def main() -> int:
    manifest = (SRC / "blender_manifest.toml").read_text()
    version = re.search(r'^version = "(.+)"', manifest, re.M)[1]
    out = ROOT / "dist" / f"free_plugin_blender-{version}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SRC.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(SRC).as_posix())
    print(f"built {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
