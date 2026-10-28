""""Render scene" as the input of a generation: a real render (Workbench here), sent to the edit endpoint."""

import os
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402
from fakes import fake_fal, last_call  # noqa: E402


def test():
    harness.enable()
    fal, net, scene_utils = harness.module(".providers.fal"), harness.module(".net"), harness.module(".scene")
    png, glb = harness.fixture_files()
    fal.request_json = fake_fal
    net.download = harness.module(".operators").net.download = harness.fake_download(png, glb)
    fal.time.sleep = lambda _s: None
    os.environ["FAL_KEY"] = "test-key"

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 160, 90, 100
    props = scene.free_plugin
    harness.module(".params")._sync_all_scenes()

    camera = scene.camera
    scene.camera = None
    try:
        scene_utils.render_scene(harness.module(".prefs").output_dir("captures") / "x.png")
        refused = False
    except RuntimeError as error:
        refused = "no active camera" in str(error)
    harness.check("no camera: told why", refused)
    scene.camera = camera

    props.image_reference = "RENDER"
    harness.check("render switches to the edit endpoint", props.image_model.loaded.endswith("/edit"),
                  props.image_model.loaded)
    bpy.ops.freeplugin.generate_image(prompt="make it night")
    harness.wait()
    model, body = last_call()
    harness.check("render sent as the image", model.endswith("/edit") and body.get("image_urls"), body.keys())
    renders = list(harness.module(".prefs").output_dir("captures").glob("*-render.png"))
    harness.check("render saved in captures", len(renders) == 1, renders)
    image = bpy.data.images.load(str(renders[0]))
    harness.check("full render at the scene resolution", tuple(image.size) == (160, 90), tuple(image.size))

    props.video_source = "RENDER"
    harness.check("video: render uses the image-to-video endpoint",
                  props.video_model.loaded.endswith("image-to-video"), props.video_model.loaded)


harness.run(test)
