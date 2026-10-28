"""Free Plugin Blender: generation with your own keys (fal.ai, Meshy) + free Poly Haven.

AI control of Blender is left to an MCP add-on (Blender Lab's "MCP" extension)
driven by Claude Code; every feature here is a `bpy.ops.freeplugin.*` operator
that such a client can call.
"""

import bpy

from . import catalog, chat, operators, overlay, panels, params, prefs, props, tasks, ui_controls

_classes = (prefs.FreePluginPreferences, *ui_controls.classes[1:], *operators.classes, *panels.classes)


def register():
    props.register()
    for cls in _classes:
        bpy.utils.register_class(cls)
    catalog.configure(prefs.user_dir())
    tasks.register()
    params.register_handlers()
    chat.register()
    overlay.register()


def unregister():
    overlay.unregister()
    chat.unregister()
    params.unregister_handlers()
    tasks.unregister()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    props.unregister()
