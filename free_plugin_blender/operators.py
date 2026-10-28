"""The buttons. Each operator reads `scene.free_plugin`; keyword arguments override the panel.

They return immediately and finish in the background (see `tasks.py`), which
also makes them callable from an MCP client:

    bpy.ops.freeplugin.generate_image(prompt="a moroccan riad courtyard at dusk")
    bpy.ops.freeplugin.generate_3d(prompt="a clay tagine", model="trellis")
    bpy.ops.freeplugin.generate_video(prompt="slow dolly in", model="kling25_turbo",
                                      options='{"duration": "10"}')
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import bpy

from . import account, catalog, chat, controls, library, net, prefs, scene, tasks, ui_controls
from .providers import fal, meshy, polyhaven

TEXTURE_PROMPT = ("Seamless tileable PBR albedo texture of {}, flat even lighting, "
                  "no shadows, no perspective, top-down orthographic, edges tile perfectly")


def _stamp(prompt, ext):
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40] or "result"
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.{ext}"


class _ModelChoice:
    """What to call: (endpoint, schema or None, options) resolved on the main thread."""

    def __init__(self, entry, endpoint, options, extra, slot="", choices=None):
        self.entry, self.endpoint = entry, endpoint
        self.schema = catalog.cached_schema(endpoint) if endpoint else None
        self.options, self.extra = options, extra
        self.slot, self.choices = slot, choices or {}

    def run(self, task, key, kind, out_dir, label, *, prompt=None, images=(), square=False):
        """Worker thread: call fal.ai and download the output file."""
        schema = self.schema or catalog.fetch_schema(self.endpoint)
        names = {f["name"] for f in schema.get("fields", [])}
        options = {k: v for k, v in self.options.items() if k in names}
        options.update(controls.resolve(self.slot, self.choices, schema, self.entry))
        if square:
            options = fal.square_options(schema, options)
        options.update(self.extra)
        payload = fal.build_payload(schema, options, prompt=prompt, image_uris=[net.data_uri(p) for p in images])
        result = fal.run(self.endpoint, payload, key, task.set)
        url = fal.result_url(result, kind)
        task.set("downloading…")
        return net.download(url, out_dir / _stamp(label, fal.extension(url, kind)))


class _Generate(bpy.types.Operator):
    bl_options = {"REGISTER"}
    prompt: bpy.props.StringProperty(name="Prompt", options={"SKIP_SAVE"})
    model: bpy.props.StringProperty(
        name="Model", options={"SKIP_SAVE"},
        description="Catalog key (e.g. seedream45, kling3_pro, trellis) or any fal.ai model id; "
                    "empty: the panel's choice",
    )
    options: bpy.props.StringProperty(
        name="Options", options={"SKIP_SAVE"},
        description='Extra model options as JSON, e.g. {"duration": "10"}',
    )

    def resolve_prompt(self, fallback):
        prompt = (self.prompt or fallback).strip()
        if not prompt:
            self.report({"ERROR"}, "Write a prompt first")
        return prompt

    def choose(self, context, slot_name, with_image, *, use_override=True) -> _ModelChoice:
        slot = getattr(context.scene.free_plugin, f"{slot_name}_model")
        if use_override and self.model:
            entry = catalog.get(slot_name, self.model) or catalog.custom_entry(self.model)
            options = dict(entry.get("defaults", {}))
        else:
            entry = slot.entry()
            if entry is None:
                raise RuntimeError("Choose a model (or paste a fal.ai model id)")
            options = slot.payload()
        endpoint = catalog.endpoint(entry, with_image)
        if endpoint is None and not entry.get("provider"):
            raise RuntimeError(f"{entry['label']} needs an input image")
        extra = json.loads(self.options) if use_override and self.options else {}
        return _ModelChoice(entry, endpoint, options, extra, slot_name,
                            ui_controls.get_choices(context.scene, slot_name))

    def input_image(self, choice_value, path_value):
        """CAMERA → capture now, FILE → check the path, anything else → None."""
        if choice_value == "CAMERA":
            return scene.capture_camera(prefs.output_dir("captures") / _stamp("camera", "png"))
        if choice_value == "FILE":
            path = Path(bpy.path.abspath(path_value))
            if not path.is_file():
                raise RuntimeError("Choose an existing image file")
            return path
        return None


class FREEPLUGIN_OT_generate_image(_Generate):
    bl_idname = "freeplugin.generate_image"
    bl_label = "Generate image"
    bl_description = "Text or image → image with the chosen fal.ai model"

    def execute(self, context):
        props = context.scene.free_plugin
        prompt = self.resolve_prompt(props.image_prompt)
        if not prompt:
            return {"CANCELLED"}
        try:
            reference = self.input_image(props.image_reference, props.image_reference_path)
            choice = self.choose(context, "image", reference is not None)
        except (RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        key, placement, folder = prefs.fal_key(), props.image_placement, prefs.output_dir("images")

        def work(task):
            images = [reference] if reference else []
            return choice.run(task, key, "image", folder, prompt, prompt=prompt, images=images)

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
    bl_description = "Generate a seamless texture with the image model and apply it to the active object"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        props = context.scene.free_plugin
        subject = self.resolve_prompt(props.texture_prompt)
        if not subject:
            return {"CANCELLED"}
        try:
            choice = self.choose(context, "image", False)
        except (RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        obj_name, tiling = context.active_object.name, props.texture_tiling
        key, folder = prefs.fal_key(), prefs.output_dir("textures")

        def work(task):
            return choice.run(task, key, "image", folder, subject, prompt=TEXTURE_PROMPT.format(subject), square=True)

        def done(task, path):
            obj = bpy.data.objects.get(obj_name)
            if obj is None:
                return str(path)
            return scene.build_material(obj, subject[:60], {"base_color": path}, tiling=tiling, bump_from_color=True)

        tasks.run(f"Texture: {subject[:40]}", work, done)
        return {"FINISHED"}


class FREEPLUGIN_OT_generate_video(_Generate):
    bl_idname = "freeplugin.generate_video"
    bl_label = "Generate video"
    bl_description = "Text or camera view → video with the chosen fal.ai model, added to the Video Sequencer"

    def execute(self, context):
        props = context.scene.free_plugin
        prompt = self.resolve_prompt(props.video_prompt)
        if not prompt:
            return {"CANCELLED"}
        try:
            start = self.input_image(props.video_source, "")
            choice = self.choose(context, "video", start is not None)
        except (RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        key, folder = prefs.fal_key(), prefs.output_dir("videos")

        def work(task):
            return choice.run(task, key, "video", folder, prompt, prompt=prompt, images=[start] if start else [])

        def done(task, path):
            scene.add_movie_strip(path)
            return str(path)

        tasks.run(f"Video: {prompt[:40]}", work, done)
        return {"FINISHED"}


class FREEPLUGIN_OT_generate_3d(_Generate):
    bl_idname = "freeplugin.generate_3d"
    bl_label = "Generate 3D model"
    bl_description = "Text, image or camera view → textured model, imported at the 3D cursor"

    def execute(self, context):
        props = context.scene.free_plugin
        prompt = (self.prompt or props.mesh_prompt).strip()
        try:
            if props.mesh_source == "TEXT" and not prompt:
                raise RuntimeError("Write a prompt first")
            image = self.input_image(props.mesh_source, props.mesh_image_path)
            choice = self.choose(context, "mesh", image is not None)
            # Image-only models (TRELLIS…) get a reference picture drawn by the image model.
            needs_reference = image is None and choice.entry.get("text") is None and not choice.entry.get("provider")
            reference_choice = self.choose(context, "image", False, use_override=False) if needs_reference else None
        except (RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        label = prompt or image.stem
        folder = prefs.output_dir("models")
        cursor = context.scene.cursor.location.copy()

        if choice.entry.get("provider") == "meshy":
            key, texture, pbr = prefs.meshy_key(), props.mesh_texture, props.mesh_pbr

            def work(task):
                if image:
                    result = meshy.image_to_3d(net.data_uri(image), key, texture=texture, pbr=pbr, progress=task.set)
                else:
                    result = meshy.text_to_3d(prompt, key, texture=texture, pbr=pbr, progress=task.set)
                task.set("downloading…")
                path = net.download(meshy.glb_url(result), folder / _stamp(label, "glb"))
                return {"meshy_task_id": result["id"]}, path
        else:
            key, images_folder = prefs.fal_key(), prefs.output_dir("images")

            def work(task):
                source = image
                if reference_choice is not None:
                    task.set("drawing a reference image…")
                    source = reference_choice.run(task, key, "image", images_folder, label + "-reference",
                                                  prompt=prompt + fal.OBJECT_REFERENCE_SUFFIX, square=True)
                path = choice.run(task, key, "mesh", folder, label,
                                  prompt=None if source else prompt, images=[source] if source else [])
                return {"fal_model": choice.endpoint}, path

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


class FREEPLUGIN_OT_load_model(bpy.types.Operator):
    bl_idname = "freeplugin.load_model"
    bl_label = "Load model options"
    bl_description = "Read the model's options from fal.ai"

    slot: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        from . import params

        if self.slot not in catalog.SLOTS:
            return {"CANCELLED"}
        params.sync_slot(context.scene, self.slot, force=True)
        return {"FINISHED"}


class FREEPLUGIN_OT_open_catalog(bpy.types.Operator):
    bl_idname = "freeplugin.open_catalog"
    bl_label = "Open my models.json"
    bl_description = "Add your own models to the menus (same format as the bundled catalog)"

    def execute(self, context):
        bpy.ops.wm.path_open(filepath=str(catalog.user_catalog_path()))
        return {"FINISHED"}


class FREEPLUGIN_OT_reload_catalog(bpy.types.Operator):
    bl_idname = "freeplugin.reload_catalog"
    bl_label = "Reload models"
    bl_description = "Re-read models.json and refresh the options of every panel"

    clear_cache: bpy.props.BoolProperty(name="Also re-download options", options={"SKIP_SAVE"})

    def execute(self, context):
        from . import params

        if self.clear_cache:
            catalog.clear_schema_cache()
        catalog.reload()
        for scene_ in bpy.data.scenes:
            for slot_name in catalog.SLOTS:
                getattr(scene_.free_plugin, f"{slot_name}_model").loaded = ""
                params.sync_slot(scene_, slot_name, force=self.clear_cache)
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
    bl_label = "Retexture"
    bl_description = ("Re-paint the active model from a text style with Meshy (on fal.ai or with your own key), "
                      "imported as a new object")

    def execute(self, context):
        props = context.scene.free_plugin
        prompt = self.resolve_prompt(props.retexture_prompt)
        if not prompt:
            return {"CANCELLED"}
        on_fal = props.retexture_provider == "FAL"
        # fal.ai cannot see our Meshy tasks, so it always gets the mesh itself.
        task_id, glb = (None, self.export_active(context)) if on_fal else self.model_source(context)
        fal_key, meshy_key, pbr = prefs.fal_key(), prefs.meshy_key(), props.retexture_pbr
        resolution = props.retexture_resolution
        out = prefs.output_dir("models") / _stamp(prompt, "glb")

        def work(task):
            uri = net.data_uri(glb, "application/octet-stream") if glb else None
            if on_fal:
                payload = {"model_url": uri, "text_style_prompt": prompt, "enable_pbr": pbr,
                           "texture_resolution": resolution}
                result = fal.run(fal.RETEXTURE_MODEL, payload, fal_key, task.set)
                task.set("downloading…")
                return {"fal_model": fal.RETEXTURE_MODEL}, net.download(fal.result_url(result, "mesh"), out)
            result = meshy.retexture(meshy_key, prompt, input_task_id=task_id, model_uri=uri, pbr=pbr,
                                     progress=task.set)
            return {"meshy_task_id": result["id"]}, net.download(meshy.glb_url(result), out)

        def done(task, value):
            return scene.import_glb(value[1], value[0])

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


class FREEPLUGIN_OT_library_use(bpy.types.Operator):
    bl_idname = "freeplugin.library_use"
    bl_label = "Use"
    bl_description = ("Put one of your generations in the scene: 3D and animations at the 3D cursor, "
                      "a material image on the active mesh, an image as set in Image › Put result, "
                      "a video in the Video Sequencer")
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        path = Path(self.filepath)
        entry = next((e for e in library.scan(prefs.library_roots()) if e.path == path), None)
        if entry is None or not path.is_file():
            self.report({"ERROR"}, f"Not in your generations any more: {path.name}")
            library.CACHE.clear()
            return {"CANCELLED"}
        if entry.kind in ("MESH", "ANIMATION"):
            cursor = context.scene.cursor.location.copy()
            names = scene.import_glb(path, {"free_plugin_library": str(path)})
            for name in names:
                obj = bpy.data.objects[name]
                if obj.parent is None:
                    obj.location = cursor
            self.report({"INFO"}, f"Imported {entry.name}")
        elif entry.kind == "VIDEO":
            scene.add_movie_strip(path)
            self.report({"INFO"}, f"{entry.name}: added to the Video Sequencer")
        else:
            obj = context.active_object
            if entry.folder == "textures" and obj is not None and obj.type == "MESH":
                scene.build_material(obj, entry.name[:60], {"base_color": path},
                                     tiling=context.scene.free_plugin.texture_tiling, bump_from_color=True)
                self.report({"INFO"}, f"Material {entry.name} on {obj.name}")
                return {"FINISHED"}
            image = scene.load_image(path)
            placement = context.scene.free_plugin.image_placement
            if placement == "PLANE":
                scene.image_to_plane(image, name=entry.name[:60])
            elif placement == "CAMERA_BG":
                scene.image_to_camera_background(image)
            self.report({"INFO"}, f"Loaded {entry.name}")
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


class FREEPLUGIN_OT_chat_send(bpy.types.Operator):
    bl_idname = "freeplugin.chat_send"
    bl_label = "Send"
    bl_description = "Send the message to Claude Code"

    text: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        props = context.scene.free_plugin
        text = self.text or props.chat_input
        error = chat.send(text, context.scene)
        if error:
            self.report({"WARNING"}, error)
            return {"CANCELLED"}
        if not self.text:
            props.chat_input = ""
        return {"FINISHED"}


class FREEPLUGIN_OT_chat_stop(bpy.types.Operator):
    bl_idname = "freeplugin.chat_stop"
    bl_label = "Stop"
    bl_description = "Stop Claude's current answer"

    def execute(self, context):
        chat.stop()
        return {"FINISHED"}


class FREEPLUGIN_OT_chat_reset(bpy.types.Operator):
    bl_idname = "freeplugin.chat_reset"
    bl_label = "New conversation"
    bl_description = "Forget this conversation and start a new one"

    def execute(self, context):
        chat.reset()
        return {"FINISHED"}


class FREEPLUGIN_OT_chat_transcript(bpy.types.Operator):
    bl_idname = "freeplugin.chat_transcript"
    bl_label = "Full transcript"
    bl_description = "Copy the whole conversation into the text block \"Free Plugin Chat\" (Text Editor)"

    def execute(self, context):
        name = chat.write_transcript()
        for area in context.screen.areas:
            if area.type == "TEXT_EDITOR":
                area.spaces.active.text = bpy.data.texts[name]
                break
        else:
            self.report({"INFO"}, f'Open a Text Editor and pick "{name}"')
        return {"FINISHED"}


class FREEPLUGIN_OT_claude_connect(bpy.types.Operator):
    bl_idname = "freeplugin.claude_connect"
    bl_label = "Connect my Claude subscription"
    bl_description = "Sign in with your Claude account (Pro/Max) in the browser, through Claude Code. No API key"

    def execute(self, context):
        error = account.login()
        if error:
            self.report({"WARNING"}, error)
            return {"CANCELLED"}
        self.report({"INFO"}, "Finish signing in in your browser")
        return {"FINISHED"}


class FREEPLUGIN_OT_claude_send_code(bpy.types.Operator):
    bl_idname = "freeplugin.claude_send_code"
    bl_label = "Send code"
    bl_description = "Send the code shown in the browser to finish signing in"

    def execute(self, context):
        props = context.scene.free_plugin
        error = account.send_code(props.auth_code)
        if error:
            self.report({"WARNING"}, error)
            return {"CANCELLED"}
        props.auth_code = ""
        return {"FINISHED"}


class FREEPLUGIN_OT_claude_cancel(bpy.types.Operator):
    bl_idname = "freeplugin.claude_cancel"
    bl_label = "Cancel sign-in"

    def execute(self, context):
        account.cancel_login()
        return {"FINISHED"}


class FREEPLUGIN_OT_claude_disconnect(bpy.types.Operator):
    bl_idname = "freeplugin.claude_disconnect"
    bl_label = "Disconnect"
    bl_description = "Sign out of Claude Code on this computer (also signs out the terminal claude)"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, message="Sign out of Claude Code on this computer?")

    def execute(self, context):
        error = account.logout()
        if error:
            self.report({"WARNING"}, error)
            return {"CANCELLED"}
        return {"FINISHED"}


class FREEPLUGIN_OT_claude_refresh(bpy.types.Operator):
    bl_idname = "freeplugin.claude_refresh"
    bl_label = "Check again"
    bl_description = "Look for Claude Code and its sign-in again"

    def execute(self, context):
        account.refresh(force=True)
        return {"FINISHED"}


class FREEPLUGIN_OT_claude_install(bpy.types.Operator):
    bl_idname = "freeplugin.claude_install"
    bl_label = "How to install Claude Code"
    bl_description = "Copy the install command to the clipboard and open the Claude Code page"

    def execute(self, context):
        context.window_manager.clipboard = account.INSTALL_COMMAND
        bpy.ops.wm.url_open(url=account.INSTALL_URL)
        self.report({"INFO"}, f"Copied: {account.INSTALL_COMMAND} — paste it in a terminal, then Check again")
        return {"FINISHED"}


class FREEPLUGIN_OT_api_models_refresh(bpy.types.Operator):
    bl_idname = "freeplugin.api_models_refresh"
    bl_label = "Refresh the model list"
    bl_description = "Read the provider's current models again"

    def execute(self, context):
        from . import api_models

        if not prefs.api_key():
            self.report({"ERROR"}, "Set the API key first")
            return {"CANCELLED"}
        api_models.refresh()
        return {"FINISHED"}


class FREEPLUGIN_OT_mcp_copy_command(bpy.types.Operator):
    bl_idname = "freeplugin.mcp_copy_command"
    bl_label = "Copy the terminal command"
    bl_description = ("Copy the `claude mcp add` command that connects Claude Code in a terminal to this "
                      "Blender's Free Plugin MCP server (set a fixed port first, so it keeps working)")

    def execute(self, context):
        from . import mcpserver

        if mcpserver.state.server is None:
            self.report({"ERROR"}, "The Free Plugin MCP server is off")
            return {"CANCELLED"}
        context.window_manager.clipboard = mcpserver.terminal_command()
        self.report({"INFO"}, "Copied: paste it in a terminal")
        return {"FINISHED"}


class FREEPLUGIN_OT_mcp_new_token(bpy.types.Operator):
    bl_idname = "freeplugin.mcp_new_token"
    bl_label = "New token"
    bl_description = "Replace the Free Plugin MCP token (terminals set up with the old one stop working)"

    def execute(self, context):
        from . import mcpserver

        prefs.get().own_mcp_token = ""
        mcpserver.stop()
        mcpserver.sync()
        return {"FINISHED"}


class FREEPLUGIN_OT_open_url(bpy.types.Operator):
    bl_idname = "freeplugin.open_url"
    bl_label = "Open"
    bl_options = {"INTERNAL"}

    url: bpy.props.StringProperty()

    def execute(self, context):
        bpy.ops.wm.url_open(url=self.url)
        return {"FINISHED"}


class FREEPLUGIN_OT_open_outputs(bpy.types.Operator):
    bl_idname = "freeplugin.open_outputs"
    bl_label = "Open output folder"

    def execute(self, context):
        bpy.ops.wm.path_open(filepath=str(prefs.output_dir()))  # creates ~/Kiln if needed
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
    FREEPLUGIN_OT_load_model,
    FREEPLUGIN_OT_open_catalog,
    FREEPLUGIN_OT_reload_catalog,
    FREEPLUGIN_OT_retexture,
    FREEPLUGIN_OT_rig,
    FREEPLUGIN_OT_polyhaven_search,
    FREEPLUGIN_OT_polyhaven_apply,
    FREEPLUGIN_OT_library_use,
    FREEPLUGIN_OT_local_remesh,
    FREEPLUGIN_OT_local_lods,
    FREEPLUGIN_OT_chat_send,
    FREEPLUGIN_OT_chat_stop,
    FREEPLUGIN_OT_chat_reset,
    FREEPLUGIN_OT_chat_transcript,
    FREEPLUGIN_OT_claude_connect,
    FREEPLUGIN_OT_claude_send_code,
    FREEPLUGIN_OT_claude_cancel,
    FREEPLUGIN_OT_claude_disconnect,
    FREEPLUGIN_OT_claude_refresh,
    FREEPLUGIN_OT_claude_install,
    FREEPLUGIN_OT_api_models_refresh,
    FREEPLUGIN_OT_mcp_copy_command,
    FREEPLUGIN_OT_mcp_new_token,
    FREEPLUGIN_OT_open_url,
    FREEPLUGIN_OT_open_outputs,
    FREEPLUGIN_OT_clear_tasks,
)
