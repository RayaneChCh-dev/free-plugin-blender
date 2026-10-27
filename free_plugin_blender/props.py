"""Panel settings, stored on the scene as `scene.free_plugin`."""

from __future__ import annotations

import bpy

from .providers import fal

MESH_PROVIDERS = [
    (key, f"{spec['label']} {spec['cost']}",
     "fal.ai" if "text" in spec else "fal.ai, image only: a text prompt is drawn by Seedream first (+$0.04)")
    for key, spec in fal.MODELS_3D.items()
] + [("MESHY", "Meshy (own key, credits)", "Meshy API with your own key and credits")]

IMAGE_SIZES = [
    ("auto_2K", "Auto 2K", ""),
    ("square_hd", "Square", ""),
    ("landscape_16_9", "16:9", ""),
    ("portrait_16_9", "9:16", ""),
    ("landscape_4_3", "4:3", ""),
    ("portrait_4_3", "3:4", ""),
]


class FreePluginAsset(bpy.types.PropertyGroup):
    asset_id: bpy.props.StringProperty()


class FreePluginProps(bpy.types.PropertyGroup):
    # Image
    image_prompt: bpy.props.StringProperty(name="Prompt")
    image_size: bpy.props.EnumProperty(name="Size", items=IMAGE_SIZES)
    image_reference: bpy.props.EnumProperty(
        name="Reference",
        items=[("NONE", "None", "Text only"),
               ("CAMERA", "Camera view", "Edit a render of the active camera"),
               ("FILE", "Image file", "Edit an image from disk")],
    )
    image_reference_path: bpy.props.StringProperty(name="Image", subtype="FILE_PATH")
    image_placement: bpy.props.EnumProperty(
        name="Put result",
        items=[("PLANE", "On a plane", ""), ("CAMERA_BG", "Camera background", ""), ("NONE", "Image only", "")],
    )

    # Texture
    texture_prompt: bpy.props.StringProperty(name="Material", default="weathered sandstone wall")
    texture_tiling: bpy.props.FloatProperty(name="Tiling", default=1.0, min=0.01, soft_max=20.0)

    # Video
    video_prompt: bpy.props.StringProperty(name="Prompt")
    video_source: bpy.props.EnumProperty(
        name="Start from",
        items=[("CAMERA", "Camera view", "Animate a render of the active camera"), ("TEXT", "Text only", "")],
    )
    video_duration: bpy.props.IntProperty(name="Seconds", default=5, min=3, max=15)
    video_aspect: bpy.props.EnumProperty(
        name="Aspect", items=[("16:9", "16:9", ""), ("9:16", "9:16", ""), ("1:1", "1:1", "")]
    )
    video_audio: bpy.props.BoolProperty(name="Audio", default=False)

    # 3D
    mesh_provider: bpy.props.EnumProperty(name="Model", items=MESH_PROVIDERS)
    mesh_prompt: bpy.props.StringProperty(name="Prompt")
    mesh_source: bpy.props.EnumProperty(
        name="From",
        items=[("TEXT", "Text", ""), ("FILE", "Image file", ""), ("CAMERA", "Camera view", "")],
    )
    mesh_image_path: bpy.props.StringProperty(name="Image", subtype="FILE_PATH")
    mesh_texture: bpy.props.BoolProperty(name="Texture", default=True)
    mesh_pbr: bpy.props.BoolProperty(name="PBR maps", default=True)
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


classes = (FreePluginAsset, FreePluginProps)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.free_plugin = bpy.props.PointerProperty(type=FreePluginProps)


def unregister():
    del bpy.types.Scene.free_plugin
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
