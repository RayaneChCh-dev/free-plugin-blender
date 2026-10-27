"""API keys, model ids and output folder, in Preferences > Add-ons."""

from __future__ import annotations

import os
from pathlib import Path

import bpy

from .providers import fal

ADDON_ID = __package__


class FreePluginPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    fal_key: bpy.props.StringProperty(
        name="fal.ai key", subtype="PASSWORD",
        description="From https://fal.ai/dashboard/keys (env var FAL_KEY also works)",
    )
    meshy_key: bpy.props.StringProperty(
        name="Meshy key (optional)", subtype="PASSWORD",
        description="From https://www.meshy.ai/settings/api (env var MESHY_API_KEY also works)",
    )
    image_model: bpy.props.StringProperty(name="Text → image", default=fal.IMAGE_MODEL)
    edit_model: bpy.props.StringProperty(name="Image edit", default=fal.EDIT_MODEL)
    video_t2v_model: bpy.props.StringProperty(name="Text → video", default=fal.VIDEO_T2V_MODEL)
    video_i2v_model: bpy.props.StringProperty(name="Image → video", default=fal.VIDEO_I2V_MODEL)
    output_dir: bpy.props.StringProperty(
        name="Output folder", subtype="DIR_PATH",
        description="Where generated files are saved (empty: the extension's user folder)",
    )
    show_video: bpy.props.BoolProperty(
        name="Show video panel", default=False,
        description="AI video is the most expensive feature (~$0.14/s with Kling 3.0 Pro); "
                    "the operator stays callable from scripts and MCP either way",
    )

    def draw(self, context):
        layout = self.layout
        col = layout.column(heading="Keys")
        col.prop(self, "fal_key")
        col.prop(self, "meshy_key")
        layout.prop(self, "output_dir")
        layout.prop(self, "show_video")
        box = layout.box()
        box.label(text="fal.ai model ids (any id from fal.ai/models)")
        for name in ("image_model", "edit_model", "video_t2v_model", "video_i2v_model"):
            box.prop(self, name)


def get():
    return bpy.context.preferences.addons[ADDON_ID].preferences


def fal_key():
    return get().fal_key.strip() or os.environ.get("FAL_KEY", "").strip()


def meshy_key():
    return get().meshy_key.strip() or os.environ.get("MESHY_API_KEY", "").strip()


def output_dir(*parts) -> Path:
    configured = get().output_dir.strip()
    if configured:
        root = Path(bpy.path.abspath(configured))
    else:
        try:
            root = Path(bpy.utils.extension_path_user(ADDON_ID, path="outputs", create=True))
        except (AttributeError, ValueError):  # legacy add-on install
            root = Path.home() / "free-plugin-blender"
    path = root.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
