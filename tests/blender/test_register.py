import sys
from pathlib import Path

import addon_utils
import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402


def test():
    harness.enable()
    harness.check("enabled", harness.MODULE in bpy.context.preferences.addons)
    ops = set(dir(bpy.ops.freeplugin))
    for name in ("generate_image", "generate_texture", "generate_video", "generate_3d", "rig", "retexture",
                 "polyhaven_search", "polyhaven_apply", "local_remesh", "local_lods", "reload_catalog"):
        harness.check(f"operator {name}", name in ops)
    harness.check("scene settings", hasattr(bpy.context.scene, "free_plugin"))
    harness.check("main panel", hasattr(bpy.types, "FREEPLUGIN_PT_main"))
    addon_utils.disable(harness.MODULE)
    harness.check("disabled cleanly", not hasattr(bpy.types.Scene, "free_plugin"))


harness.run(test)
