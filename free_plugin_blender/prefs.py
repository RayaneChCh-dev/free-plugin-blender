"""API keys and output folder, in Preferences > Add-ons. Models are chosen in the panels."""

from __future__ import annotations

import os
from pathlib import Path

import bpy

from . import claude_models

ADDON_ID = __package__


def _overlay_toggled(self, context):
    from . import overlay

    if self.overlay_enabled:
        overlay.mount()
    else:
        overlay.unmount()


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

    overlay_enabled: bpy.props.BoolProperty(
        name="Viewport prompt bar", default=True, update=_overlay_toggled,
        description="Show the prompt bar at the bottom of the 3D view",
    )
    claude_path: bpy.props.StringProperty(
        name="Claude Code path", subtype="FILE_PATH",
        description="Path to the `claude` command (empty: look it up on PATH and in ~/.local/bin)",
    )
    chat_model: bpy.props.EnumProperty(
        name="Claude model",
        description="Model the chat uses",
        items=[(key, label, text, 100 + index) for index, (key, label, text) in enumerate(claude_models.MODELS)],
        default=claude_models.DEFAULT_MODEL,
    )
    chat_effort: bpy.props.EnumProperty(
        name="Effort",
        description="How much Claude thinks before acting. More effort: better on hard scenes, slower, more usage",
        items=[(key, label, text, 200 + index) for index, (key, label, text) in enumerate(claude_models.EFFORTS)],
        default=claude_models.DEFAULT_EFFORT,
    )
    mcp_command: bpy.props.StringProperty(
        name="Blender MCP command", default="uvx mcp-for-blender",
        description="MCP server Claude uses to reach this Blender (it connects to the MCP add-on's port)",
    )
    mcp_port: bpy.props.IntProperty(
        name="MCP add-on port", default=9876, min=1, max=65535,
        description="Port of the Blender MCP add-on in this Blender (passed to the MCP server)",
    )

    def draw(self, context):
        from . import chat, panels

        layout = self.layout

        box = layout.box()
        box.label(text="1 · Claude — chat and scene building, with your subscription", icon="USER")
        panels.draw_claude_account(box)
        row = box.row()
        row.prop(self, "chat_model")
        row.prop(self, "chat_effort")

        box = layout.box()
        box.label(text="2 · fal.ai — image, material, 3D and video generation (pay per use)", icon="IMAGE_DATA")
        row = box.row(align=True)
        row.prop(self, "fal_key")
        row.operator("freeplugin.open_url", text="Get a key", icon="URL").url = "https://fal.ai/dashboard/keys"
        box.label(text="Optional: the chat, Poly Haven and mesh tools work without it.", icon="INFO")
        row = box.row(align=True)
        row.prop(self, "meshy_key")
        row.operator("freeplugin.open_url", text="", icon="URL").url = "https://www.meshy.ai/settings/api"
        box.label(text="Meshy is only needed for Retexture.", icon="INFO")

        box = layout.box()
        box.label(text="3 · Blender MCP — lets Claude act on this scene", icon="LINKED")
        if chat.state.mcp_listening:
            box.label(text=f"MCP add-on listening on port {self.mcp_port}", icon="CHECKMARK")
        else:
            box.label(text=f"Nothing listens on port {self.mcp_port}: enable the Blender MCP add-on", icon="ERROR")
            box.operator("freeplugin.open_url", text="Get the mcp-for-blender add-on",
                         icon="URL").url = "https://pypi.org/project/mcp-for-blender/"
        box.prop(self, "mcp_command")
        box.prop(self, "mcp_port")

        box = layout.box()
        box.label(text="Display and files", icon="WINDOW")
        box.prop(self, "overlay_enabled")
        box.prop(self, "show_video")
        box.prop(self, "output_dir")

        box = layout.box()
        box.label(text="Models: chosen in the sidebar. Add your own fal.ai models:", icon="PRESET")
        row = box.row()
        row.operator("freeplugin.open_catalog", icon="TEXT")
        row.operator("freeplugin.reload_catalog", icon="FILE_REFRESH")
        box.operator("freeplugin.reload_catalog", text="Re-download model options",
                     icon="URL").clear_cache = True

        box = layout.box()
        box.label(text="Advanced", icon="TOOL_SETTINGS")
        box.prop(self, "claude_path")


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
