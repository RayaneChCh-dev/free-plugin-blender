"""Assets › My generations: files in the output folder go back into the scene."""

import shutil
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402


def test():
    harness.enable()
    prefs, library = harness.module(".prefs"), harness.module(".library")
    png, glb = harness.fixture_files()
    root = prefs.output_root()
    harness.check("tests write to a throwaway folder", root != prefs.DEFAULT_OUTPUT and root.is_dir(), root)
    harness.check("~/Kiln is the default", prefs.DEFAULT_OUTPUT == Path.home() / "Kiln")

    model = prefs.output_dir("models") / "20261028-101500-a-clay-tagine-pot.glb"
    image = prefs.output_dir("images") / "20261028-090000-riad-courtyard.png"
    texture = prefs.output_dir("textures") / "20261028-091000-green-zellige.png"
    for source, target in ((glb, model), (png, image), (png, texture)):
        shutil.copy(source, target)
    found = library.scan(prefs.library_roots())
    harness.check("generations listed", {e.name for e in found} >= {"a clay tagine pot", "riad courtyard",
                                                                      "green zellige"}, [e.name for e in found])

    scene = bpy.context.scene
    scene.cursor.location = (2.0, 0.0, 0.0)
    before = set(bpy.data.objects)
    harness.check("3D model imported", bpy.ops.freeplugin.library_use(filepath=str(model)) == {"FINISHED"})
    new = [o for o in bpy.data.objects if o not in before]
    harness.check("at the 3D cursor", new and all(o.location.x == 2.0 for o in new if o.parent is None),
                  [tuple(o.location) for o in new])

    scene.free_plugin.image_placement = "PLANE"
    before = set(bpy.data.objects)
    bpy.ops.freeplugin.library_use(filepath=str(image))
    planes = [o for o in bpy.data.objects if o not in before]
    harness.check("image on a plane", len(planes) == 1 and planes[0].type == "MESH", planes)

    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    bpy.ops.freeplugin.library_use(filepath=str(texture))
    harness.check("material image on the active mesh", cube.active_material is not None
                  and cube.active_material.name.startswith("green zellige"), cube.active_material)

    missing = prefs.output_dir("images") / "gone.png"
    try:
        result = bpy.ops.freeplugin.library_use(filepath=str(missing))
    except RuntimeError:
        result = {"CANCELLED"}
    harness.check("a file that is gone is refused", result == {"CANCELLED"})


harness.run(test)
