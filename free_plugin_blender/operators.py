"""The buttons. Each operator reads `scene.free_plugin`; `prompt=` overrides the panel's prompt.

They return immediately and finish in the background (see `tasks.py`), which
also makes them callable from an MCP client:

    bpy.ops.freeplugin.generate_image(prompt="a moroccan riad courtyard at dusk")
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import bpy

from . import net, prefs, scene, tasks
from .providers import fal, meshy, polyhaven


def _stamp(prompt, ext):
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40] or "result"
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.{ext}"


class _Generate(bpy.types.Operator):
    bl_options = {"REGISTER"}
    prompt: bpy.props.StringProperty(name="Prompt", options={"SKIP_SAVE"})

    def resolve_prompt(self, fallback):
        prompt = (self.prompt or fallback).strip()
        if not prompt:
            self.report({"ERROR"}, "Write a prompt first")
        return prompt


class FREEPLUGIN_OT_generate_image(_Generate):
    bl_idname = "freeplugin.generate_image"
    bl_label = "Generate image"
    bl_description = "Text or image → image with fal.ai (Seedream 4.5 by default, ~$0.04)"

    def execute(self, context):
        props = context.scene.free_plugin
        prompt = self.resolve_prompt(props.image_prompt)
        if not prompt:
            return {"CANCELLED"}
        settings = prefs.get()
        key = prefs.fal_key()
        out = prefs.output_dir("images") / _stamp(prompt, "png")

        reference = None
        try:
            if props.image_reference == "CAMERA":
                reference = scene.capture_camera(prefs.output_dir("captures") / _stamp("camera", "png"))
            elif props.image_reference == "FILE":
                reference = Path(bpy.path.abspath(props.image_reference_path))
                if not reference.is_file():
                    raise RuntimeError("Choose an existing reference image")
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        model = settings.edit_model if reference else settings.image_model
        size, placement = props.image_size, props.image_placement

        def work(task):
            uris = [net.data_uri(reference)] if reference else []
            result = fal.run(model, fal.image_payload(prompt, size, uris), key, task.set)
            task.set("downloading…")
            return net.download(fal.first_image_url(result), out)

        def done(task, path):
            image = scene.load_image(path)
            if placement == "PLANE":
                scene.image_to_plane(image, name=path.stem[:60])
            elif placement == "CAMERA_BG":
                scene.image_to_camera_background(image)
            return str(path)

        tasks.run(f"Image: {prompt[:40]}", work, done)
        return {"FINISHED"}


class FREEPLUGIN_OT_generate_texture(_Generate):
    bl_idname = "freeplugin.generate_texture"
    bl_label = "Generate material"
    bl_description = "Generate a seamless texture with fal.ai and apply it to the active object (~$0.04)"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        props = context.scene.free_plugin
        subject = self.resolve_prompt(props.texture_prompt)
        if not subject:
            return {"CANCELLED"}
        obj_name = context.active_object.name
        key, model, tiling = prefs.fal_key(), prefs.get().image_model, props.texture_tiling
        out = prefs.output_dir("textures") / _stamp(subject, "png")
        prompt = (f"Seamless tileable PBR albedo texture of {subject}, flat even lighting, "
                  "no shadows, no perspective, top-down orthographic, edges tile perfectly")

        def work(task):
            payload = fal.image_payload(prompt, {"width": 2048, "height": 2048})
            result = fal.run(model, payload, key, task.set)
            task.set("downloading…")
            return net.download(fal.first_image_url(result), out)

        def done(task, path):
            obj = bpy.data.objects.get(obj_name)
            if obj is None:
                return str(path)
            return scene.build_material(obj, subject[:60], {"base_color": path},
                                        tiling=tiling, bump_from_color=True)

        tasks.run(f"Texture: {subject[:40]}", work, done)
        return {"FINISHED"}


class FREEPLUGIN_OT_generate_video(_Generate):
    bl_idname = "freeplugin.generate_video"
    bl_label = "Generate video"
    bl_description = "Text or camera view → video with fal.ai (Kling 3.0 Pro by default, ~$0.14/s), added to the Video Sequencer"

    def execute(self, context):
        props = context.scene.free_plugin
        prompt = self.resolve_prompt(props.video_prompt)
        if not prompt:
            return {"CANCELLED"}
        settings = prefs.get()
        start = None
        if props.video_source == "CAMERA":
            try:
                start = scene.capture_camera(prefs.output_dir("captures") / _stamp("camera", "png"))
            except RuntimeError as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
        model = settings.video_i2v_model if start else settings.video_t2v_model
        key = prefs.fal_key()
        duration, aspect, audio = props.video_duration, props.video_aspect, props.video_audio
        out = prefs.output_dir("videos") / _stamp(prompt, "mp4")

        def work(task):
            uri = net.data_uri(start) if start else None
            payload = fal.video_payload(model, prompt, duration, aspect, audio, uri)
            result = fal.run(model, payload, key, task.set)
            task.set("downloading…")
            return net.download(fal.video_url(result), out)

        def done(task, path):
            scene.add_movie_strip(path)
            return str(path)

        tasks.run(f"Video: {prompt[:40]}", work, done)
        return {"FINISHED"}


class FREEPLUGIN_OT_generate_3d(_Generate):
    bl_idname = "freeplugin.generate_3d"
    bl_label = "Generate 3D model"
    bl_description = "Text, image or camera view → textured GLB (fal.ai or Meshy), imported at the 3D cursor"

    provider: bpy.props.StringProperty(
        name="Model", options={"SKIP_SAVE"},
        description="TRELLIS, TRELLIS2, TRIPO, HUNYUAN or MESHY (empty: the panel's choice)",
    )

    def execute(self, context):
        props = context.scene.free_plugin
        source = props.mesh_source
        prompt = (self.prompt or props.mesh_prompt).strip()
        provider = self.provider or props.mesh_provider
        if provider != "MESHY" and provider not in fal.MODELS_3D:
            self.report({"ERROR"}, f"Unknown 3D model {provider!r}")
            return {"CANCELLED"}
        image = None
        try:
            if source == "TEXT":
                if not prompt:
                    raise RuntimeError("Write a prompt first")
            elif source == "CAMERA":
                image = scene.capture_camera(prefs.output_dir("captures") / _stamp("camera", "png"))
            else:
                image = Path(bpy.path.abspath(props.mesh_image_path))
                if not image.is_file():
                    raise RuntimeError("Choose an existing image")
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        texture, pbr = props.mesh_texture, props.mesh_pbr
        label = prompt or image.stem
        out = prefs.output_dir("models") / _stamp(label, "glb")
        cursor = context.scene.cursor.location.copy()

        if provider == "MESHY":
            key = prefs.meshy_key()

            def work(task):
                if image:
                    result = meshy.image_to_3d(net.data_uri(image), key, texture=texture, pbr=pbr, progress=task.set)
                else:
                    result = meshy.text_to_3d(prompt, key, texture=texture, pbr=pbr, progress=task.set)
                task.set("downloading…")
                return {"meshy_task_id": result["id"]}, net.download(meshy.glb_url(result), out)
        else:
            key, spec, image_model = prefs.fal_key(), fal.MODELS_3D[provider], prefs.get().image_model
            reference = prefs.output_dir("images") / _stamp(label + "-reference", "png")

            def work(task):
                image_uri = net.data_uri(image) if image else None
                if image_uri is None and "text" not in spec:
                    task.set("drawing a reference image…")
                    result = fal.run(image_model, fal.image_payload(prompt + fal.OBJECT_REFERENCE_SUFFIX, "square_hd"),
                                     key, task.set)
                    image_uri = net.data_uri(net.download(fal.first_image_url(result), reference))
                model = spec["image"] if image_uri else spec["text"]
                payload = fal.model_3d_payload(spec, prompt=prompt, image_uri=image_uri, pbr=texture and pbr)
                result = fal.run(model, payload, key, task.set)
                task.set("downloading…")
                return {"fal_model": model}, net.download(fal.glb_url(result), out)

        def done(task, value):
            tag, path = value
            names = scene.import_glb(path, tag)
            for name in names:
                obj = bpy.data.objects[name]
                if obj.parent is None:
                    obj.location = cursor
            return names

        tasks.run(f"3D: {label[:40]}", work, done)
        return {"FINISHED"}


class _MeshyOnActive(_Generate):
    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type in {"MESH", "EMPTY"}

    def model_source(self, context):
        """(input_task_id, glb_path): reuse the Meshy task when the object came from Meshy."""
        task_id = context.active_object.get("meshy_task_id")
        return (task_id, None) if task_id else (None, self.export_active(context))

    def export_active(self, context):
        obj = context.active_object
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        return scene.export_selected_glb(prefs.output_dir("exports") / _stamp(obj.name, "glb"))


class FREEPLUGIN_OT_retexture(_MeshyOnActive):
    bl_idname = "freeplugin.retexture"
    bl_label = "Retexture with Meshy"
    bl_description = "Re-paint the active model from a text style with Meshy, imported as a new object"

    def execute(self, context):
        prompt = self.resolve_prompt(context.scene.free_plugin.retexture_prompt)
        if not prompt:
            return {"CANCELLED"}
        task_id, glb = self.model_source(context)
        key = prefs.meshy_key()
        out = prefs.output_dir("models") / _stamp(prompt, "glb")

        def work(task):
            uri = net.data_uri(glb, "application/octet-stream") if glb else None
            result = meshy.retexture(key, prompt, input_task_id=task_id, model_uri=uri, progress=task.set)
            return result["id"], net.download(meshy.glb_url(result), out)

        def done(task, value):
            return scene.import_glb(value[1], {"meshy_task_id": value[0]})

        tasks.run(f"Retexture: {prompt[:40]}", work, done)
        return {"FINISHED"}


class FREEPLUGIN_OT_rig(_MeshyOnActive):
    bl_idname = "freeplugin.rig"
    bl_label = "Auto-rig"
    bl_description = ("Rig the active humanoid with Meshy (on fal.ai or with your own key) "
                      "and import it with walk/run clips. The character must face -Y in Blender")

    def execute(self, context):
        props = context.scene.free_plugin
        on_fal = props.rig_provider == "FAL"
        # fal.ai cannot see our Meshy tasks, so it always gets the mesh itself.
        task_id, glb = (None, self.export_active(context)) if on_fal else self.model_source(context)
        fal_key, meshy_key, height = prefs.fal_key(), prefs.meshy_key(), props.rig_height
        folder = prefs.output_dir("rigs")
        name = context.active_object.name

        def work(task):
            uri = net.data_uri(glb, "application/octet-stream") if glb else None
            if on_fal:
                result = fal.run(fal.RIG_MODEL, {"model_url": uri, "height_meters": height}, fal_key, task.set)
                urls = fal.rig_urls(result)
            else:
                result = meshy.rig(meshy_key, input_task_id=task_id, model_uri=uri,
                                   height_meters=height, progress=task.set)
                payload = result.get("result") or {}
                clips = payload.get("basic_animations") or {}
                urls = [payload["rigged_character_glb_url"], clips.get("walking_glb_url"), clips.get("running_glb_url")]
            task.set("downloading…")
            return [net.download(url, folder / _stamp(f"{name}-{suffix}", "glb"))
                    for url, suffix in zip(urls, ("rigged", "walking", "running")) if url]

        def done(task, files):
            return [n for path in files for n in scene.import_glb(path)]

        tasks.run(f"Rig: {name}", work, done)
        return {"FINISHED"}


class FREEPLUGIN_OT_polyhaven_search(bpy.types.Operator):
    bl_idname = "freeplugin.polyhaven_search"
    bl_label = "Search Poly Haven"
    bl_description = "Search free CC0 HDRIs, textures and 3D models"

    def execute(self, context):
        props = context.scene.free_plugin
        kind, query, scene_name = props.ph_kind, props.ph_query, context.scene.name

        def done(task, hits):
            props = bpy.data.scenes[scene_name].free_plugin
            props.ph_results.clear()
            for asset_id, name in hits:
                item = props.ph_results.add()
                item.name, item.asset_id = name, asset_id
            props.ph_index = 0
            return len(hits)

        tasks.run(f"Poly Haven: {query or kind}", lambda task: polyhaven.search(kind, query), done)
        return {"FINISHED"}


class FREEPLUGIN_OT_polyhaven_apply(bpy.types.Operator):
    bl_idname = "freeplugin.polyhaven_apply"
    bl_label = "Apply"
    bl_description = "HDRI → world lighting, texture → material on the active object, model → imported at the 3D cursor"

    asset_id: bpy.props.StringProperty(options={"SKIP_SAVE"})
    kind: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        props = context.scene.free_plugin
        asset_id = self.asset_id
        if not asset_id and 0 <= props.ph_index < len(props.ph_results):
            asset_id = props.ph_results[props.ph_index].asset_id
        if not asset_id:
            self.report({"ERROR"}, "Search and pick an asset first")
            return {"CANCELLED"}
        kind, res = self.kind or props.ph_kind, props.ph_resolution
        folder = prefs.output_dir("polyhaven", asset_id)

        if kind == "hdris":
            def work(task):
                url = polyhaven.hdri_url(asset_id, res)
                return net.download(url, folder / url.rsplit("/", 1)[-1])

            tasks.run(f"HDRI: {asset_id}", work, lambda task, path: scene.set_world_hdri(path))
            return {"FINISHED"}

        if kind == "models":
            cursor = context.scene.cursor.location.copy()

            def work(task):
                gltf_url, includes = polyhaven.model_files(asset_id, res)
                for relative, url in includes.items():
                    task.set(f"downloading {relative}…")
                    net.download(url, folder / relative)
                return net.download(gltf_url, folder / gltf_url.rsplit("/", 1)[-1])

            def done(task, path):
                names = scene.import_glb(path, {"polyhaven_id": asset_id})
                for name in names:
                    obj = bpy.data.objects[name]
                    if obj.parent is None:
                        obj.location = cursor
                return names

            tasks.run(f"Model: {asset_id}", work, done)
            return {"FINISHED"}

        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh to receive the texture")
            return {"CANCELLED"}
        obj_name, tiling = obj.name, props.texture_tiling

        def work(task):
            maps = {}
            for role, url in polyhaven.texture_urls(asset_id, res).items():
                task.set(f"downloading {role}…")
                maps[role] = net.download(url, folder / url.rsplit("/", 1)[-1])
            return maps

        def done(task, maps):
            maps.pop("displacement", None)
            return scene.build_material(bpy.data.objects[obj_name], asset_id, maps, tiling=tiling)

        tasks.run(f"Texture: {asset_id}", work, done)
        return {"FINISHED"}


class FREEPLUGIN_OT_local_remesh(bpy.types.Operator):
    bl_idname = "freeplugin.local_remesh"
    bl_label = "Voxel remesh"
    bl_description = "Add a voxel Remesh modifier (free, runs in Blender)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        scene.local_remesh(context.active_object, context.scene.free_plugin.remesh_voxel)
        return {"FINISHED"}


class FREEPLUGIN_OT_local_lods(bpy.types.Operator):
    bl_idname = "freeplugin.local_lods"
    bl_label = "Make LODs"
    bl_description = "Create hidden 50% / 25% / 10% decimated copies (free, runs in Blender)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        names = scene.local_lods(context.active_object)
        self.report({"INFO"}, "Created " + ", ".join(names))
        return {"FINISHED"}


class FREEPLUGIN_OT_open_outputs(bpy.types.Operator):
    bl_idname = "freeplugin.open_outputs"
    bl_label = "Open output folder"

    def execute(self, context):
        bpy.ops.wm.path_open(filepath=str(prefs.output_dir()))
        return {"FINISHED"}


class FREEPLUGIN_OT_clear_tasks(bpy.types.Operator):
    bl_idname = "freeplugin.clear_tasks"
    bl_label = "Clear finished"

    def execute(self, context):
        tasks.TASKS[:] = [t for t in tasks.TASKS if t.state == "running"]
        return {"FINISHED"}


classes = (
    FREEPLUGIN_OT_generate_image,
    FREEPLUGIN_OT_generate_texture,
    FREEPLUGIN_OT_generate_video,
    FREEPLUGIN_OT_generate_3d,
    FREEPLUGIN_OT_retexture,
    FREEPLUGIN_OT_rig,
    FREEPLUGIN_OT_polyhaven_search,
    FREEPLUGIN_OT_polyhaven_apply,
    FREEPLUGIN_OT_local_remesh,
    FREEPLUGIN_OT_local_lods,
    FREEPLUGIN_OT_open_outputs,
    FREEPLUGIN_OT_clear_tasks,
)
