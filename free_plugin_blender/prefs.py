"""API keys and output folder, in Preferences > Add-ons. Models are chosen in the panels."""

from __future__ import annotations

import os
from pathlib import Path

import bpy

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
        box.label(text="Models are chosen in the sidebar panels. Add your own:")
        row = box.row()
        row.operator("freeplugin.open_catalog", icon="TEXT")
        row.operator("freeplugin.reload_catalog", icon="FILE_REFRESH")
        box.operator("freeplugin.reload_catalog", text="Re-download model options",
                     icon="URL").clear_cache = True


def get():
    return bpy.context.preferences.addons[ADDON_ID].preferences


def fal_key():
    return get().fal_key.strip() or os.environ.get("FAL_KEY", "").strip()


def meshy_key():
    return get().meshy_key.strip() or os.environ.get("MESHY_API_KEY", "").strip()


def user_dir() -> Path:
    """The extension's own writable folder (catalog, schema cache, default outputs)."""
    try:
        return Path(bpy.utils.extension_path_user(ADDON_ID, create=True))
    except (AttributeError, ValueError):  # legacy add-on install
        path = Path.home() / "free-plugin-blender"
        path.mkdir(exist_ok=True)
        return path


def output_dir(*parts) -> Path:
    configured = get().output_dir.strip()
    root = Path(bpy.path.abspath(configured)) if configured else user_dir() / "outputs"
    path = root.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
