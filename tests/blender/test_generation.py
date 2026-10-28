"""Every generation path with fal.ai and Poly Haven replaced by fakes (no network, no key)."""

import json
import os
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402

calls = []


def fake_fal(method, url, headers=None, body=None, timeout=60):
    if method == "POST":
        model = url.split("queue.fal.run/")[1]
        calls.append((model, body))
        fake_fal.current = model
        return {"status_url": "https://q/r/status", "response_url": "https://q/r"}
    if url.endswith("/status"):
        return {"status": "COMPLETED"}
    model = fake_fal.current
    if "video" in model or "veo" in model:
        return {"video": {"url": "https://x/out.mp4", "content_type": "video/mp4"}}
    if "trellis" in model:
        return {"model_mesh": {"url": "https://x/m.glb"}}
    if "tripo" in model:
        return {"model_mesh": {"url": "https://x/m.fbx"}, "model_urls": {"glb": {"url": "https://x/m.glb"}}}
    if "rigging" in model:
        return {"rigged_character_glb": {"url": "https://x/r.glb"}, "basic_animations": {}}
    return {"images": [{"url": "https://x/i.png", "content_type": "image/png"}]}


def fake_polyhaven(method, url, headers=None, body=None, timeout=60):
    if "/assets" in url:
        return {"sunset_a": {"name": "Sunset A", "tags": ["sunset"], "categories": [], "download_count": 5},
                "brick_b": {"name": "Brick B", "tags": ["brick"], "categories": [], "download_count": 3}}
    asset = url.rsplit("/", 1)[-1]
    if asset == "sunset_a":
        return {"hdri": {"1k": {"hdr": {"url": "https://x/sunset_a_1k.hdr"}}}}
    return {"Diffuse": {"1k": {"jpg": {"url": "https://x/b_diff.png"}}},
            "nor_gl": {"1k": {"jpg": {"url": "https://x/b_nor.png"}}}}


def last_call():
    return calls[-1] if calls else (None, {})


def test():
    harness.enable()
    fal, net = harness.module(".providers.fal"), harness.module(".net")
    polyhaven, params = harness.module(".providers.polyhaven"), harness.module(".params")
    png, glb = harness.fixture_files()
    fal.request_json, polyhaven.request_json = fake_fal, fake_polyhaven
    net.download = fake_download = harness.fake_download(png, glb)
    harness.module(".operators").net.download = fake_download
    fal.time.sleep = lambda _s: None
    os.environ["FAL_KEY"] = "test-key"

    scene = bpy.context.scene
    props = scene.free_plugin
    params._sync_all_scenes()
    harness.check("image options loaded", props.image_model.loaded.endswith("text-to-image"), props.image_model.loaded)

    # Image, then the same model's edit endpoint once a reference is set.
    next(p for p in props.image_model.params if p.name == "image_size").e = "landscape_16_9"
    bpy.ops.freeplugin.generate_image(prompt="riad courtyard")
    harness.wait()
    model, body = last_call()
    harness.check("text → image call", model.endswith("text-to-image") and body["prompt"] == "riad courtyard", body)
    harness.check("only changed options are sent", body.get("image_size") == "landscape_16_9" and "seed" not in body)
    props.image_reference, props.image_reference_path = "FILE", str(png)
    harness.check("reference switches to the edit endpoint", props.image_model.loaded.endswith("/edit"))
    bpy.ops.freeplugin.generate_image(prompt="at night")
    harness.wait()
    model, body = last_call()
    harness.check("edit call carries the image", model.endswith("/edit") and body["image_urls"][0].startswith("data:"))
    props.image_reference = "NONE"

    # Material on the active mesh, square.
    bpy.ops.mesh.primitive_plane_add()
    bpy.ops.freeplugin.generate_texture(prompt="zellige")
    harness.wait()
    plane = bpy.context.active_object
    harness.check("texture asks for a square", last_call()[1].get("image_size") == "square_hd")
    harness.check("material applied", plane.data.materials and plane.data.materials[0].name.startswith("zellige"))

    # Video from text, with a model override and options as JSON (the MCP path).
    props.video_source = "TEXT"
    bpy.ops.freeplugin.generate_video(prompt="dolly", model="kling25_turbo", options='{"duration": "10"}')
    harness.wait()
    model, body = last_call()
    harness.check("video override + options", "v2.5-turbo" in model and body.get("duration") == "10", (model, body))
    strips = scene.sequence_editor.strips if scene.sequence_editor else []
    harness.check("video added to the sequencer", len(strips) == 1)

    # 3D: image-only model from text goes through a reference image.
    props.mesh_source = "TEXT"
    before = len(calls)
    bpy.ops.freeplugin.generate_3d(prompt="tagine", model="trellis")
    done = harness.wait()
    chain = [m for m, _ in calls[before:]]
    harness.check("text → image → TRELLIS", len(chain) == 2 and chain[1] == "fal-ai/trellis", chain)
    harness.check("model imported", done and done[0].state == "done" and done[0].result, done and done[0].detail)
    bpy.ops.freeplugin.generate_3d(prompt="tagine", model="tripo")
    harness.wait()
    harness.check("Tripo takes the text directly", last_call()[0] == "tripo3d/h3.1/text-to-3d")

    # Rig through fal.ai.
    props.rig_provider = "FAL"
    bpy.context.view_layer.objects.active = plane
    bpy.ops.freeplugin.rig()
    harness.wait()
    harness.check("rig sends the mesh", last_call()[0] == "fal-ai/meshy/rigging"
                  and last_call()[1]["model_url"].startswith("data:"))

    # Unknown key: a clear task error, no crash.
    os.environ["FAL_KEY"] = ""
    bpy.ops.freeplugin.generate_image(prompt="no key")
    done = harness.wait()
    harness.check("missing key is reported", done and done[0].state == "error" and "fal.ai key" in done[0].detail)

    # Poly Haven: search, HDRI → world, texture → material.
    props.ph_kind, props.ph_query = "hdris", "sunset"
    bpy.ops.freeplugin.polyhaven_search()
    harness.wait()
    harness.check("search filters by tag", [r.asset_id for r in props.ph_results] == ["sunset_a"])
    props.ph_resolution = "1k"
    bpy.ops.freeplugin.polyhaven_apply(asset_id="sunset_a", kind="hdris")
    harness.wait()
    nodes = scene.world.node_tree.nodes
    harness.check("HDRI on the world", any(n.type == "TEX_ENVIRONMENT" and n.image for n in nodes))
    bpy.context.view_layer.objects.active = plane  # the rig import changed the active object
    bpy.ops.freeplugin.polyhaven_apply(asset_id="brick_b", kind="textures")
    harness.wait()
    material = plane.data.materials[0]
    harness.check("PBR material with normal map", any(n.type == "NORMAL_MAP" for n in material.node_tree.nodes))

    # Local tools.
    bpy.ops.freeplugin.local_lods()
    harness.check("LODs created", f"{plane.name}_LOD3" in bpy.data.objects)
    bpy.ops.freeplugin.local_remesh()
    harness.check("remesh modifier", any(m.type == "REMESH" for m in plane.modifiers))

    # User catalog reload.
    catalog = harness.module(".catalog")
    path = catalog.user_catalog_path()
    data = json.loads(path.read_text())
    data["image"].append({"key": "mine", "label": "Mine", "text": "fal-ai/flux/schnell"})
    path.write_text(json.dumps(data))
    bpy.ops.freeplugin.reload_catalog()
    harness.check("user model in the menu", catalog.get("image", "mine") is not None)


harness.run(test)
