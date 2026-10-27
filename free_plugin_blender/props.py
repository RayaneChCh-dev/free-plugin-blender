"""Panel settings, stored on the scene as `scene.free_plugin`."""

from __future__ import annotations

import bpy

from . import params


def _source_changed(self, context):
    # Text vs image input can switch the endpoint, and with it the options.
    if context is not None and context.scene is not None:
        params.sync_scene(context.scene)


class FreePluginAsset(bpy.types.PropertyGroup):
    asset_id: bpy.props.StringProperty()


class FreePluginProps(bpy.types.PropertyGroup):
    image_model: bpy.props.PointerProperty(type=params.SLOT_CLASSES["image"])
    video_model: bpy.props.PointerProperty(type=params.SLOT_CLASSES["video"])
    mesh_model: bpy.props.PointerProperty(type=params.SLOT_CLASSES["mesh"])

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

    # Local
    remesh_voxel: bpy.props.FloatProperty(name="Voxel size", default=0.02, min=0.001, soft_max=0.5, unit="LENGTH")


classes = (*params.classes, FreePluginAsset, FreePluginProps)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.free_plugin = bpy.props.PointerProperty(type=FreePluginProps)


def unregister():
    del bpy.types.Scene.free_plugin
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
