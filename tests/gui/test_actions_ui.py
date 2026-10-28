"""The action row under a generated image in the bar: shown, Make 3D switches tab, material needs a mesh."""

import shutil
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from sim import check, click, module, rect, run  # noqa: E402

REPORT, IMAGE = sys.argv[-2], sys.argv[-1]
bar, prefs, tasks = module(".overlay"), module(".prefs"), module(".tasks")


def ids():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return [r[0] for r in bar.state.rects.get(region.as_pointer(), [])]


def finished_image():
    path = prefs.output_dir("images") / "20261028-090000-riad-courtyard.png"
    shutil.copy(IMAGE, path)
    task = tasks.Task("Image: riad courtyard")
    task.state, task.result, task.detail = "done", str(path), "done"
    tasks.TASKS.insert(0, task)
    state["path"] = str(path)


def no_selection():
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = None


state = {}

run([
    finished_image,
    lambda: click(rect("pill")),
    lambda: click(rect("tab:image")),
    lambda: check("three actions under the image", {"act:MATERIAL", "act:MESH", "act:SCENE"} <= set(ids()), ids()),
    lambda: click(rect("tab:mesh")),
    lambda: check("not shown on other tabs", "act:MESH" not in ids()),
    lambda: click(rect("tab:image")),
    no_selection,
    lambda: click(rect("act:MATERIAL")),
    lambda: check("material without a mesh: told why", "Select a mesh" in bar.state.notice[0], bar.state.notice),
    lambda: click(rect("act:MESH")),
    lambda: check("Make 3D opens the 3D tab with the image", bar.state.mode == "mesh"
                  and bpy.context.scene.free_plugin.mesh_source == "FILE"
                  and bpy.context.scene.free_plugin.mesh_image_path == state["path"]),
    lambda: check("the image shows as the 3D input", any(i.startswith("attach") for i in ids()), ids()),
], REPORT)
