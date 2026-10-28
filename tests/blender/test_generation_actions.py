"""Actions on a generated image: material, 3D tab with the image attached, scene built by Claude (fake)."""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402

FAKE = harness.FIXTURES / "fakeclaude"
STATE = Path(tempfile.mkdtemp(prefix="fakeclaude-"))
os.environ["FAKE_CLAUDE_STATE"] = str(STATE)


def test():
    harness.enable()
    chat, account, overlay = harness.module(".chat"), harness.module(".account"), harness.module(".overlay")
    prefs = bpy.context.preferences.addons[harness.MODULE].preferences
    prefs.claude_path, prefs.mcp_port, prefs.mcp_mode = str(FAKE / "claude"), 9877, "EXTERNAL"
    account.account.logged_in = True

    # A big generated image, as fal.ai returns them.
    big = harness.module(".prefs").output_dir("images") / "20261028-090000-riad-courtyard.png"
    image = bpy.data.images.new("big", 3000, 1500)
    image.filepath_raw, image.file_format = str(big), "PNG"
    image.save()
    bpy.data.images.remove(image)

    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    bpy.ops.freeplugin.use_generation(filepath=str(big), action="MATERIAL")
    harness.check("material on the active mesh", cube.active_material is not None
                  and cube.active_material.name.startswith("riad courtyard"), cube.active_material)

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = None
    try:
        bpy.ops.freeplugin.use_generation(filepath=str(big), action="MATERIAL")
        refused = False
    except RuntimeError as error:
        refused = "Select a mesh" in str(error)
    harness.check("material needs a mesh", refused)

    props = bpy.context.scene.free_plugin
    bpy.ops.freeplugin.use_generation(filepath=str(big), action="MESH")
    harness.check("3D tab gets the image", props.mesh_source == "FILE" and props.mesh_image_path == str(big))
    harness.check("bar opens on 3D, nothing spent", overlay.state.mode == "mesh" and overlay.state.expanded
                  and not harness.module(".tasks").TASKS)

    bpy.ops.freeplugin.use_generation(filepath=str(big), action="SCENE")
    end = time.time() + 20
    while chat.state.busy and time.time() < end:
        time.sleep(0.05)
    chat._tick()
    call = json.loads((STATE / "last_call.json").read_text())
    argv = call["argv"]
    harness.check("JSON input when an image is attached", argv[argv.index("--input-format") + 1] == "stream-json")
    event = json.loads(call["stdin"])
    blocks = event["message"]["content"]
    harness.check("text then image", [b["type"] for b in blocks] == ["text", "image"], [b["type"] for b in blocks])
    harness.check("asks to build the scene, then about materials", "Build a 3D scene" in blocks[0]["text"]
                  and "textures and materials" in blocks[0]["text"])
    thumb = harness.module(".prefs").output_dir("captures") / "20261028-090000-riad-courtyard-for-claude.jpg"
    small = bpy.data.images.load(str(thumb))
    harness.check("image shrunk for the message", max(small.size) == 1568 and blocks[1]["source"]["media_type"]
                  == "image/jpeg", tuple(small.size))
    shown = [m["text"] for m in chat.state.messages if m["role"] == "user"][-1]
    harness.check("conversation names the attachment", shown.endswith("Attached: " + thumb.name), shown)
    harness.check("bar on the Scene tab", overlay.state.mode == "scene")

    chat.send("Thanks", bpy.context.scene)
    end = time.time() + 20
    while chat.state.busy and time.time() < end:
        time.sleep(0.05)
    argv = json.loads((STATE / "last_call.json").read_text())["argv"]
    harness.check("plain messages stay plain text", "--input-format" not in argv)


harness.run(test)
