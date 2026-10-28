"""Animation tab: presets (Meshy rigging on fal.ai), motion from text (Hunyuan), copy a motion. Fakes only."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402
import rigs  # noqa: E402
from fakes import fake_fal, last_call  # noqa: E402


def select(*objects, active=None):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


def fixtures():
    """What fake fal.ai sends back: an animated Meshy-named character (GLB) and an SMPL motion (FBX)."""
    folder = Path(tempfile.mkdtemp())
    character = rigs.animate(rigs.meshy("MeshyOut", location=(0, 0, 0)), rigs.MESHY_NAMES)
    body = rigs.skin(character, "MeshyBody")
    glb = folder / "animation.glb"
    select(character, body, active=character)
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=True)
    motion = rigs.animate(rigs.smpl("HunyuanOut"))
    fbx = folder / "motion.fbx"
    select(motion, active=motion)
    bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True, object_types={"ARMATURE"},
                             bake_anim=True, add_leaf_bones=False)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    return {"animation.glb": glb, "motion.fbx": fbx}


def test():
    harness.enable()
    fal, net = harness.module(".providers.fal"), harness.module(".net")
    animation, presets = harness.module(".animation"), harness.module(".presets")
    files = fixtures()

    def download(url, dest, timeout=300):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files[url.rsplit("/", 1)[-1]], dest)
        return dest

    fal.request_json, fal.time.sleep = fake_fal, lambda _s: None
    net.download = animation.net.download = download
    os.environ["FAL_KEY"] = "test-key"
    scene = bpy.context.scene
    props = scene.free_plugin
    animation._fill_presets()
    harness.check("preset list filled", len(props.anim_results) == len(presets.all_presets()))

    # Filters.
    props.anim_category = "Dancing"
    harness.check("category filter", props.anim_results and all(
        presets.get(i.preset_id)["category"] == "Dancing" for i in props.anim_results))
    props.anim_category, props.anim_in_place = "ALL", True
    harness.check("in place filter", props.anim_results and all(i.in_place for i in props.anim_results))
    props.anim_in_place, props.anim_query = False, "walk"
    harness.check("search", props.anim_results and all("walk" in f"{i.name} {i.sub}".lower() or "walkandrun" in
                  presets.get(i.preset_id)["category"].lower() for i in props.anim_results))

    # Nothing selected: presets need a character.
    select(active=None)
    harness.check("preset needs a character", not bpy.ops.freeplugin.animate_preset.poll())

    # A mesh without rig: Meshy rigs and animates it, the rigged character replaces it.
    bpy.ops.mesh.primitive_cube_add(size=1, location=(1, 1, 0.9))
    hero = bpy.context.active_object
    hero.name, hero.scale = "Hero", (0.4, 0.3, 1.8)
    first = presets.all_presets()[0]
    bpy.ops.freeplugin.animate_preset(preset_id=first["id"])
    done = harness.wait()
    model, body = last_call()
    harness.check("rigging call with the preset", model == "fal-ai/meshy/rigging" and body["enable_animation"]
                  and body["animation_action_id"] == first["id"] and body["model_url"].startswith("data:"), body)
    harness.check("height from the mesh", abs(body["height_meters"] - 1.8) < 0.01, body["height_meters"])
    harness.check("preset applied", done and done[0].state == "done", done and done[0].detail)
    rig = bpy.context.active_object
    harness.check("rigged character is active", rig is not None and rig.type == "ARMATURE"
                  and rig.get(animation.CHARACTER_TAG) == "Hero", rig)
    harness.check("action named after the preset", rig.animation_data.action.name == first["name"])
    harness.check("original mesh hidden", hero.hide_get() and hero.hide_render)
    harness.check("placed where the mesh stood", (rig.location.xy - hero.location.xy).length < 1e-3
                  and abs(rig.location.z) < 1e-3, rig.location)
    harness.check("panel sees the rig", animation.character(rig)[1] == rig)

    # Next preset (picked in the list) goes onto the same rig as a new action.
    props.anim_index = 0
    picked = presets.get(props.anim_results[0].preset_id)
    count = len(bpy.data.objects)
    bpy.ops.freeplugin.animate_preset()
    done = harness.wait()
    harness.check("second preset retargeted", done and done[0].state == "done", done and done[0].detail)
    harness.check("list choice sent", last_call()[1]["animation_action_id"] == picked["id"])
    harness.check("new action on the same rig", rig.animation_data.action.name == picked["name"])
    harness.check("first action kept", first["name"] in bpy.data.actions
                  and bpy.data.actions[first["name"]].use_fake_user)
    harness.check("downloaded character removed", len(bpy.data.objects) == count, len(bpy.data.objects) - count)
    harness.check("rig stays active", bpy.context.active_object == rig, bpy.context.active_object)

    # Motion from text onto the rig.
    bpy.ops.freeplugin.generate_motion(prompt="a joyful jump", duration=3)
    done = harness.wait()
    model, body = last_call()
    harness.check("Hunyuan call", model == "fal-ai/hunyuan-motion" and body == {
        "prompt": "a joyful jump", "duration": 3.0, "output_format": "fbx"}, body)
    harness.check("motion retargeted", done and done[0].state == "done", done and done[0].detail)
    harness.check("motion is the rig's action", rig.animation_data.action.name == "a joyful jump")
    harness.check("mannequin removed", len(bpy.data.objects) == count)
    harness.check("timeline covers the motion", scene.frame_end >= rigs.FRAMES)

    # No rig: the mannequin is kept, at the 3D cursor.
    select(active=None)
    scene.cursor.location = (-3, 0, 0)
    props.motion_prompt, props.motion_duration = "spin", 2.0
    bpy.ops.freeplugin.generate_motion()
    done = harness.wait()
    harness.check("panel prompt and duration", last_call()[1]["prompt"] == "spin"
                  and last_call()[1]["duration"] == 2.0, last_call()[1])
    mannequin = bpy.context.active_object
    harness.check("mannequin kept", mannequin is not None and mannequin.type == "ARMATURE" and mannequin != rig
                  and mannequin.animation_data.action.name == "spin", mannequin)
    harness.check("mannequin at the cursor", (mannequin.location - scene.cursor.location).length < 1e-3)

    # Copy: the mannequin's motion onto the rig, free.
    select(rig, active=rig)
    harness.check("copy needs a second animated rig", not bpy.ops.freeplugin.copy_motion.poll())
    select(mannequin, rig, active=rig)
    result = bpy.ops.freeplugin.copy_motion()
    harness.check("copy motion", result == {"FINISHED"} and rig.animation_data.action.name.startswith("spin"),
                  rig.animation_data.action.name)

    # Errors are reported, not raised.
    os.environ["FAL_KEY"] = ""
    bpy.ops.freeplugin.generate_motion(prompt="no key")
    done = harness.wait()
    harness.check("missing key is reported", done and done[0].state == "error" and "fal.ai key" in done[0].detail)
    try:
        bpy.ops.freeplugin.animate_preset(preset_id=999999)
    except RuntimeError as error:
        harness.check("unknown preset is refused", "Pick a preset" in str(error), error)
    harness.check("unknown preset: nothing started", not harness.wait())


harness.run(test)
