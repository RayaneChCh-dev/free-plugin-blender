#!/usr/bin/env python3
"""Run tests/gui/test_*.py in a visible Blender window with simulated input (needs a display).

Not part of CI. Usage: python3 scripts/run_gui_tests.py --blender /path/to/blender
A Blender window opens and closes by itself; your real Blender settings are not touched.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--blender", default=os.environ.get("BLENDER", shutil.which("blender") or "blender"))
    args = parser.parse_args()

    subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py")], check=True)
    zip_path = max((ROOT / "dist").glob("free_plugin_blender-*.zip"), key=lambda p: p.stat().st_mtime)
    work = Path(tempfile.mkdtemp(prefix="fpb-gui-"))
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(work / "profile")}
    subprocess.run([args.blender, "--factory-startup", "-b", "--command", "extension", "install-file",
                    "-r", "user_default", str(zip_path)], env=env, check=True, capture_output=True)
    # A saved startup file avoids the splash screen; a small PNG to pick in the file browser.
    start, image = work / "start.blend", work / "pick-me.png"
    subprocess.run([args.blender, "--factory-startup", "-b", "--python-expr",
                    "import bpy\n"
                    f"bpy.ops.wm.save_as_mainfile(filepath={str(start)!r})\n"
                    "i = bpy.data.images.new('p', 16, 16)\n"
                    f"i.filepath_raw = {str(image)!r}; i.file_format = 'PNG'; i.save()"],
                   env=env, check=True, capture_output=True)

    failed = 0
    for test in sorted((ROOT / "tests" / "gui").glob("test_*.py")):
        report = work / f"{test.stem}.json"
        subprocess.run([args.blender, "--factory-startup", "--enable-event-simulate", str(start),
                        "--python", str(test), "--", str(report), str(image)],
                       env=env, capture_output=True, timeout=240)
        results = json.loads(report.read_text()) if report.exists() else [("FAIL", "no report", "")]
        print(f"=== {test.name}")
        for status, name, detail in results:
            print(status, name, detail)
        failed += sum(1 for status, *_ in results if status != "PASS")
    shutil.rmtree(work, ignore_errors=True)
    print("All GUI checks passed" if not failed else f"{failed} GUI check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
