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


def check_manifest(manifest: str):
    """Blender rejects permission reasons over 64 characters or ending with a period."""
    for name, reason in re.findall(r'^(network|files|clipboard|camera|microphone) = "(.*)"$', manifest, re.M):
        if len(reason) > 64 or reason.endswith("."):
            raise SystemExit(f"blender_manifest.toml: permission {name!r} reason must be <= 64 chars, no final period")


def main() -> int:
    manifest = (SRC / "blender_manifest.toml").read_text()
    check_manifest(manifest)
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
