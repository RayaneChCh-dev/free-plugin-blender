"""Assets › My generations in the viewport bar: listed, filtered as you type, a click adds it to the scene."""

import shutil
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from sim import check, click, module, rect, run, type_text  # noqa: E402

REPORT, IMAGE = sys.argv[-2], sys.argv[-1]
bar, prefs = module(".overlay"), module(".prefs")


def props():
    return bpy.context.scene.free_plugin


def items():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return [r[0] for r in bar.state.rects.get(region.as_pointer(), []) if r[0].startswith("lib:")]


def fill_library():
    shutil.copy(IMAGE, prefs.output_dir("images") / "20261028-090000-riad-courtyard.png")
    shutil.copy(IMAGE, prefs.output_dir("images") / "20261028-090500-desert-dunes.png")
    bpy.ops.mesh.primitive_cube_add()
    glb = prefs.output_dir("models") / "20261028-101500-a-clay-tagine-pot.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=True)
    bpy.data.objects.remove(bpy.context.active_object)
    module(".library").CACHE.clear()


state = {}

run([
    fill_library,
    lambda: click(rect("pill")),
    lambda: click(rect("tab:assets")),
    lambda: check("Poly Haven by default, with a source chip", props().assets_source == "POLYHAVEN"
                  and rect("source") is not None),
    lambda: setattr(props(), "assets_source", "MINE"),
    lambda: None,
    lambda: check("three generations listed", len(items()) == 3, items()),
    lambda: check("filter chip says All", bar._model_label(bpy.context, "assets") == "All"),
    lambda: setattr(props(), "lib_filter", "IMAGE"),
    lambda: None,
    lambda: check("Images filter: two", len(items()) == 2, items()),
    lambda: setattr(props(), "lib_filter", "ALL"),
    lambda: click(rect("text")),
    lambda: type_text("tagine"),
    lambda: None,
    lambda: check("typing filters by name", len(items()) == 1 and bar.state.library[0].kind == "MESH",
                  [e.name for e in bar.state.library]),
    lambda: state.update(before=set(bpy.data.objects)),
    lambda: click(rect("lib:0")),
    lambda: None,
    lambda: check("click imports the model", any(o not in state["before"] for o in bpy.data.objects)),
], REPORT)
