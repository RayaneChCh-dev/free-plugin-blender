#!/usr/bin/env python3
"""Measure the tokens the Scene chat uses in each MCP mode, with the real Claude Code.

Not part of CI: it uses your Claude subscription (each run is one real chat turn) and
needs a display. Each run gets a fresh throwaway Blender; mcp-for-blender listens on
port 9877, never on your Blender's 9876.

Usage: python3 scripts/bench_mcp_modes.py --blender /path/to/blender [--model claude-haiku-5-5]
       [--modes EXTERNAL,BOTH,OWN] [--tasks build,batch,look,assets] [--repeat 1] [--out results.json]

The `generate` task is paid (fal.ai, about $0.02 a run): it needs FAL_KEY in the environment, or
--fal-key-from-prefs to read the key saved in your real Blender preferences (never printed).
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
MCP_ADDON = Path.home() / ".config" / "blender" / "5.2" / "scripts" / "addons" / "blender_mcp.py"


def tokens(usage):
    cached = usage.get("cache_read_input_tokens", 0) or 0
    written = usage.get("cache_creation_input_tokens", 0) or 0
    fresh = usage.get("input_tokens", 0) or 0
    return fresh + written + cached, cached, usage.get("output_tokens", 0) or 0


def saved_fal_key(blender, work):
    """The fal.ai key from the user's real Blender preferences, through a private file (never printed)."""
    path = work / "fal.key"
    path.touch(mode=0o600)
    subprocess.run([blender, "-b", "--python-expr",
                    "import bpy\n"
                    "a = bpy.context.preferences.addons.get('bl_ext.user_default.free_plugin_blender')\n"
                    f"open({str(path)!r}, 'w').write(a.preferences.fal_key.strip() if a else '')"],
                   check=True, capture_output=True)
    key = path.read_text().strip()
    path.unlink()
    if not key:
        sys.exit("No fal.ai key in your Blender preferences")
    return key


def table(runs):
    lines = ["| Task | Mode | Done | Turns | Tool calls | Tokens in (cached) | Tokens out | Cost (API $) | Time |",
             "|---|---|---|---|---|---|---|---|---|"]
    for run in runs:
        sent, cached, out = tokens(run.get("usage", {}))
        cost = run.get("cost_usd")
        lines.append(f"| {run['task']} | {run['mode']} | {'yes' if run.get('done') else 'NO'} "
                     f"| {run.get('turns', '?')} | {len(run.get('tools', []))} | {sent:,} ({cached:,}) | {out:,} "
                     f"| {cost:.3f} | {(run.get('duration_ms') or 0) / 1000:.0f} s |" if cost is not None else
                     f"| {run['task']} | {run['mode']} | failed: {run.get('crash', '?')[:60]} | | | | | | |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--blender", default=os.environ.get("BLENDER", shutil.which("blender") or "blender"))
    parser.add_argument("--model", default="claude-haiku-5-5")
    parser.add_argument("--modes", default="EXTERNAL,BOTH,OWN")
    parser.add_argument("--tasks", default="build,batch,look,assets")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--mcp-addon", default=str(MCP_ADDON), help="mcp-for-blender's Blender add-on (.py)")
    parser.add_argument("--out", default="")
    parser.add_argument("--fal-key-from-prefs", action="store_true",
                        help="read the fal.ai key from your Blender preferences, for the paid generate task")
    args = parser.parse_args()

    subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py")], check=True)
    zip_path = max((ROOT / "dist").glob("free_plugin_blender-*.zip"), key=lambda p: p.stat().st_mtime)
    work = Path(tempfile.mkdtemp(prefix="fpb-bench-"))
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(work / "profile")}
    if args.fal_key_from_prefs:
        env["FAL_KEY"] = saved_fal_key(args.blender, work)
    subprocess.run([args.blender, "--factory-startup", "-b", "--command", "extension", "install-file",
                    "-r", "user_default", str(zip_path)], env=env, check=True, capture_output=True)
    addons = work / "profile" / "scripts" / "addons"
    addons.mkdir(parents=True)
    shutil.copy(args.mcp_addon, addons / "blender_mcp.py")
    start = work / "start.blend"
    subprocess.run([args.blender, "--factory-startup", "-b", "--python-expr",
                    f"import bpy; bpy.ops.wm.save_as_mainfile(filepath={str(start)!r})"],
                   env=env, check=True, capture_output=True)

    runs = []
    for _ in range(args.repeat):
        for task in args.tasks.split(","):
            for mode in args.modes.split(","):
                report = work / f"{task}-{mode}.json"
                report.unlink(missing_ok=True)
                print(f"… {task} / {mode}", flush=True)
                subprocess.run([args.blender, "--factory-startup", str(start), "--python",
                                str(ROOT / "scripts" / "bench" / "driver.py"), "--",
                                mode, task, args.model, str(report)],
                               env=env, capture_output=True, timeout=1200)
                run = json.loads(report.read_text()) if report.exists() else \
                    {"task": task, "mode": mode, "crash": "no report"}
                runs.append(run)
                print(table([run]).splitlines()[-1], flush=True)
    shutil.rmtree(work, ignore_errors=True)
    print(f"\nModel: {args.model}\n\n{table(runs)}")
    if args.out:
        Path(args.out).write_text(json.dumps(runs, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
