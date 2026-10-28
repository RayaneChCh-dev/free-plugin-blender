"""Tiny test harness for scripts run inside Blender (`blender -b --python …`).

Blender runs no app timers in background mode, so `wait()` pumps the add-on's
main-thread queue by hand. `finish()` exits non-zero when a check failed, which
`--python-exit-code` turns into a failed CI step.
"""

import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

import addon_utils
import bpy

MODULE = "bl_ext.user_default.free_plugin_blender"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_failures = []
_count = 0


def enable():
    addon_utils.enable(MODULE, default_set=True, handle_error=lambda error: _fail_hard(f"enable: {error}"))
    return module


def module(name=""):
    return sys.modules[MODULE + name]


def _fail_hard(message):
    print("FAIL", message)
    sys.exit(1)


def check(name, condition, detail=""):
    global _count
    _count += 1
    print("PASS" if condition else "FAIL", name, "" if condition else f"— {detail}")
    if not condition:
        _failures.append(name)


def wait(limit=30):
    tasks = module(".tasks")
    end = time.time() + limit
    while time.time() < end:
        tasks._pump()
        if all(t.state != "running" for t in tasks.TASKS):
            break
        time.sleep(0.05)
    tasks._pump()
    done = list(tasks.TASKS)
    tasks.TASKS.clear()
    return done


def fixture_files():
    """A small PNG and GLB, made by Blender itself."""
    folder = Path(tempfile.mkdtemp())
    png = folder / "fixture.png"
    image = bpy.data.images.new("fixture", 32, 32)
    image.filepath_raw, image.file_format = str(png), "PNG"
    image.save()
    bpy.ops.mesh.primitive_cube_add()
    glb = folder / "fixture.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=True)
    bpy.data.objects.remove(bpy.context.active_object)
    return png, glb


def fake_download(png, glb):
    def download(url, dest, timeout=300):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(glb if url.split("?")[0].endswith((".glb", ".gltf")) else png, dest)
        return dest
    return download


def run(test):
    try:
        test()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        _failures.append("exception")
    finish()


def finish():
    print(f"{_count - len(_failures)}/{_count} checks passed")
    if _failures:
        print("FAILED:", ", ".join(_failures))
        sys.exit(1)
