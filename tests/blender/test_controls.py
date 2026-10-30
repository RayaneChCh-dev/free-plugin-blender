"""Simple settings (ratio, resolution, mode…) reach each model's own fields."""

import os
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402
from fakes import fake_fal, last_call  # noqa: E402


def test():
    harness.enable()
    fal, net, params = harness.module(".providers.fal"), harness.module(".net"), harness.module(".params")
    ui = harness.module(".ui_controls")
    png, glb = harness.fixture_files()
    fal.request_json = fake_fal
    net.download = harness.module(".operators").net.download = harness.fake_download(png, glb)
    fal.time.sleep = lambda _s: None
    os.environ["FAL_KEY"] = "test-key"
    scene = bpy.context.scene
    props = scene.free_plugin
    params._sync_all_scenes()
    choices = props.choices

    harness.check("everything starts on auto", set(ui.get_choices(scene, "image").values()) == {"auto"})

    # Seedream: ratio + 4K become a {width, height} object.
    choices.image_aspect, choices.image_resolution = "16:9", "4K"
    bpy.ops.freeplugin.generate_image(prompt="dunes")
    harness.wait()
    size = last_call()[1].get("image_size")
    harness.check("Seedream 16:9 4K → size object", isinstance(size, dict) and size["width"] > size["height"], size)

    # Nano Banana Pro: the same choices use its own fields.
    props.image_model.model = "nano_banana_pro"
    bpy.ops.freeplugin.generate_image(prompt="dunes")
    harness.wait()
    body = last_call()[1]
    harness.check("Nano Banana Pro → aspect_ratio + resolution",
                  body.get("aspect_ratio") == "16:9" and body.get("resolution") == "4K", body)
    _control, supported, _value, _label = ui.control_state(scene, "image", "quality")
    harness.check("quality not offered on Nano Banana Pro", supported == [])

    # Settings win over the same Advanced option.
    next(p for p in props.image_model.params if p.name == "aspect_ratio").e = "1:1"
    bpy.ops.freeplugin.generate_image(prompt="dunes")
    harness.wait()
    harness.check("setting overrides Advanced", last_call()[1].get("aspect_ratio") == "16:9")

    # 3D on Meshy 7 through fal.ai.
    props.mesh_source, props.mesh_model.model = "TEXT", "meshy7"
    choices.mesh_mode, choices.mesh_topology, choices.mesh_detail = "preview", "quad", "low"
    bpy.ops.freeplugin.generate_3d(prompt="chair")
    harness.wait()
    model, body = last_call()
    harness.check("Meshy 7 text → 3D call", model == "fal-ai/meshy/v7/text-to-3d", model)
    harness.check("mode, topology, detail mapped", body.get("mode") == "preview" and body.get("topology") == "quad"
                  and body.get("target_polycount") == 5000, body)

    # 3D with the user's own Meshy key: the same settings, no fal.ai schema.
    meshy = harness.module(".providers.meshy")
    created = []

    def fake_create(endpoint, payload, key):
        created.append(payload)
        return f"task{len(created)}"

    meshy.create = fake_create
    meshy.wait = lambda endpoint, task_id, key, progress=None: {"id": task_id, "model_urls": {"glb": "https://x/m.glb"}}
    os.environ["MESHY_API_KEY"] = "test-key"
    props.mesh_model.model = "meshy"
    harness.check("Meshy key: settings offered", all(ui.control_state(scene, "mesh", key)[1] for key in
                                                    ("mode", "model_type", "topology", "detail", "pbr")))
    harness.check("Meshy key: retired lowpoly not offered",
                  [v for v, _ in ui.control_state(scene, "mesh", "model_type")[1]] == ["standard", "smart-topology"])
    harness.check("Meshy key: no texture size setting", ui.control_state(scene, "mesh", "texture")[1] == [])
    bpy.ops.freeplugin.generate_3d(prompt="chair")
    harness.wait()
    harness.check("Meshy key: preview stops before texturing", len(created) == 1, created)
    harness.check("Meshy key: quad low remeshes", created[0].get("topology") == "quad"
                  and created[0].get("target_polycount") == 5000 and created[0].get("should_remesh") is True, created)
    created.clear()
    choices.mesh_mode, choices.mesh_model_type, choices.mesh_detail = "full", "smart-topology", "high"
    bpy.ops.freeplugin.generate_3d(prompt="chair")
    harness.wait()
    harness.check("Meshy key: full refines", [p["mode"] for p in created] == ["preview", "refine"], created)
    harness.check("Meshy key: smart topology rules", created[0].get("ai_model") == "meshy-t2.5"
                  and created[0].get("target_polycount") == 30000 and "topology" not in created[0], created)
    choices.mesh_mode = choices.mesh_model_type = choices.mesh_topology = choices.mesh_detail = "auto"

    # Video: a duration the next model lacks is dropped, not sent.
    props.video_source, props.video_model.model = "TEXT", "kling3_pro"
    choices.video_duration, choices.video_audio = "15", "on"
    bpy.ops.freeplugin.generate_video(prompt="pan")
    harness.wait()
    body = last_call()[1]
    harness.check("Kling 3: 15 s and audio on (overrides the catalog default off)",
                  body.get("duration") == "15" and body.get("generate_audio") is True, body)
    props.video_model.model = "kling25_turbo"
    bpy.ops.freeplugin.generate_video(prompt="pan")
    harness.wait()
    harness.check("Kling 2.5: unsupported 15 s dropped", "duration" not in last_call()[1], last_call()[1])

    harness.check("menu and operators registered", hasattr(bpy.types, "FREEPLUGIN_MT_control")
                  and hasattr(bpy.ops.freeplugin, "control_set"))
    bpy.ops.freeplugin.control_set(slot="image", key="format", value="webp")
    harness.check("control_set stores the choice", choices.image_format == "webp")


harness.run(test)
