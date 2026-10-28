#!/usr/bin/env python3
"""Build the add-on, install it in a throwaway Blender profile, run tests/blender/test_*.py.

Usage: python3 scripts/run_blender_tests.py [--blender /path/to/blender] [test names…]
Never touches your real Blender settings: BLENDER_USER_RESOURCES points to a temp dir.
"""

import argparse
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
    parser.add_argument("tests", nargs="*", help="test file names (default: all)")
    args = parser.parse_args()

    subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py")], check=True)
    zip_path = max((ROOT / "dist").glob("free_plugin_blender-*.zip"), key=lambda p: p.stat().st_mtime)
    validate = subprocess.run([args.blender, "--factory-startup", "-b", "--command", "extension", "validate",
                               str(zip_path)], capture_output=True, text=True)
    print(validate.stdout.strip().splitlines()[-1] if validate.stdout.strip() else validate.stderr)
    if validate.returncode != 0:
        return 1

    profile = Path(tempfile.mkdtemp(prefix="fpb-profile-"))
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(profile)}
    subprocess.run([args.blender, "--factory-startup", "-b", "--command", "extension", "install-file",
                    "-r", "user_default", str(zip_path)], env=env, check=True, capture_output=True)

    tests = sorted((ROOT / "tests" / "blender").glob("test_*.py"))
    if args.tests:
        tests = [t for t in tests if t.stem in args.tests or t.name in args.tests]
    failed = []
    for test in tests:
        print(f"\n=== {test.name}")
        result = subprocess.run([args.blender, "--factory-startup", "-b", "--python-exit-code", "1",
                                 "--python", str(test)], env=env, capture_output=True, text=True)
        lines = [line for line in result.stdout.splitlines() if line.startswith(("PASS", "FAIL", "Traceback"))
                 or "checks passed" in line or line.startswith("  File") or "Error" in line]
        print("\n".join(lines) or result.stdout[-2000:])
        if result.returncode != 0:
            failed.append(test.name)
            print(result.stderr[-2000:])
    shutil.rmtree(profile, ignore_errors=True)
    print("\nFAILED: " + ", ".join(failed) if failed else "\nAll Blender tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
