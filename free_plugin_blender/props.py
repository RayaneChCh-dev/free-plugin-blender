"""Panel settings, stored on the scene as `scene.free_plugin`."""

from __future__ import annotations

import bpy

from . import params, presets, ui_controls


def _source_changed(self, context):
    # Text vs image input can switch the endpoint, and with it the options.
    if context is not None and context.scene is not None:
        params.sync_scene(context.scene)


def _chat_input_changed(self, context):
    # Enter in the field sends; clearing it re-enters here with an empty string.
    if self.chat_input.strip() and context is not None:
        bpy.ops.freeplugin.chat_send()


def refresh_presets(self, context=None):
    """Fill the preset list from the library with the current search, category and filter."""
    self.anim_results.clear()
    for preset in presets.search(self.anim_query, self.anim_category, self.anim_in_place):
        item = self.anim_results.add()
        item.name, item.preset_id, item.sub, item.in_place = (preset["name"], preset["id"], preset["sub"],
                                                              preset["in_place"])
    self.anim_index = 0


class FreePluginAsset(bpy.types.PropertyGroup):
    asset_id: bpy.props.StringProperty()


class FreePluginPreset(bpy.types.PropertyGroup):
    preset_id: bpy.props.IntProperty()
    sub: bpy.props.StringProperty()
    in_place: bpy.props.BoolProperty()


class FreePluginProps(bpy.types.PropertyGroup):
    sidebar_tab: bpy.props.EnumProperty(
        name="Tab",
        items=[("SCENE", "Scene", "Chat with Claude and the viewport bar"),
               ("MESH", "3D", "3D models, rigging, retexture, mesh tools"),
               ("IMAGE", "Image", "Images and materials"),
               ("VIDEO", "Video", "Video generation"),
               ("ANIM", "Animation", "Animate a character: presets, motion from text, copy a motion"),
               ("ASSETS", "Assets", "Free Poly Haven HDRIs, textures and models")],
    )
    image_model: bpy.props.PointerProperty(type=params.SLOT_CLASSES["image"])
    video_model: bpy.props.PointerProperty(type=params.SLOT_CLASSES["video"])
    mesh_model: bpy.props.PointerProperty(type=params.SLOT_CLASSES["mesh"])
    choices: bpy.props.PointerProperty(type=ui_controls.FreePluginChoices)

    # Image
    image_prompt: bpy.props.StringProperty(name="Prompt")
    image_reference: bpy.props.EnumProperty(
        name="Reference",
        items=[("NONE", "None", "Text only"),
               ("CAMERA", "Camera view", "Edit a render of the active camera"),
               ("FILE", "Image file", "Edit an image from disk")],
        update=_source_changed,
    )
    image_reference_path: bpy.props.StringProperty(name="Image", subtype="FILE_PATH")
    image_placement: bpy.props.EnumProperty(
        name="Put result",
        items=[("PLANE", "On a plane", ""), ("CAMERA_BG", "Camera background", ""), ("NONE", "Image only", "")],
    )

    # Texture (uses the image model)
    texture_prompt: bpy.props.StringProperty(name="Material", default="weathered sandstone wall")
    texture_tiling: bpy.props.FloatProperty(name="Tiling", default=1.0, min=0.01, soft_max=20.0)

    # Video
    video_prompt: bpy.props.StringProperty(name="Prompt")
    video_source: bpy.props.EnumProperty(
        name="Start from",
        items=[("CAMERA", "Camera view", "Animate a render of the active camera"), ("TEXT", "Text only", "")],
        update=_source_changed,
    )

    # 3D
    mesh_prompt: bpy.props.StringProperty(name="Prompt")
    mesh_source: bpy.props.EnumProperty(
        name="From",
        items=[("TEXT", "Text", ""), ("FILE", "Image file", ""), ("CAMERA", "Camera view", "")],
        update=_source_changed,
    )
    mesh_image_path: bpy.props.StringProperty(name="Image", subtype="FILE_PATH")
    mesh_texture: bpy.props.BoolProperty(name="Texture", default=True, description="Meshy only")
    mesh_pbr: bpy.props.BoolProperty(name="PBR maps", default=True, description="Meshy only")
    retexture_prompt: bpy.props.StringProperty(name="Style")
    rig_provider: bpy.props.EnumProperty(
        name="Rig with",
        items=[("FAL", "Meshy rig on fal.ai ≈ $0.20", "Pay per use"),
               ("MESHY", "Meshy (own key, credits)", "")],
    )
    rig_height: bpy.props.FloatProperty(name="Height (m)", default=1.7, min=0.1, max=10.0)

    # Poly Haven
    ph_kind: bpy.props.EnumProperty(
        name="Type", items=[("hdris", "HDRI", ""), ("textures", "Texture", ""), ("models", "Model", "")]
    )
    ph_query: bpy.props.StringProperty(name="Search", default="")
    ph_resolution: bpy.props.EnumProperty(
        name="Resolution", items=[("1k", "1K", ""), ("2k", "2K", ""), ("4k", "4K", "")], default="2k"
    )
    ph_results: bpy.props.CollectionProperty(type=FreePluginAsset)
    ph_index: bpy.props.IntProperty()

    # Animation
    anim_query: bpy.props.StringProperty(name="Search", update=refresh_presets)
    anim_category: bpy.props.EnumProperty(
        name="Category", items=[(key, label, "") for key, label in presets.CATEGORIES], update=refresh_presets,
    )
    anim_in_place: bpy.props.BoolProperty(
        name="In place", description="Only motions that stay on the spot (no travel)", update=refresh_presets,
    )
    anim_results: bpy.props.CollectionProperty(type=FreePluginPreset)
    anim_index: bpy.props.IntProperty()
    motion_prompt: bpy.props.StringProperty(name="Motion", description="Describe the motion, e.g. a joyful jump")
    motion_duration: bpy.props.FloatProperty(name="Duration", default=5.0, min=0.5, max=12.0, unit="TIME_ABSOLUTE",
                                             description="Seconds of motion (0.5 to 12)")

    # Chat
    auth_code: bpy.props.StringProperty(name="Code", description="Paste the code shown in the browser, if asked")
    chat_input: bpy.props.StringProperty(
        name="Message", description="Press Enter to send", update=_chat_input_changed,
    )

    # Local
    remesh_voxel: bpy.props.FloatProperty(name="Voxel size", default=0.02, min=0.001, soft_max=0.5, unit="LENGTH")


classes = (*params.classes, ui_controls.FreePluginChoices, FreePluginAsset, FreePluginPreset, FreePluginProps)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.free_plugin = bpy.props.PointerProperty(type=FreePluginProps)


def unregister():
    del bpy.types.Scene.free_plugin
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
