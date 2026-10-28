"""Sidebar (N) > Free Plugin: a status header, tabs, and collapsible sections per tab.

The viewport prompt bar (overlay/) is the quick way in; this panel holds every
setting, the model options and the generation history.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import bpy

from . import account, animation, api_models, chat, library, params, prefs, presets, tasks, ui_controls

_ROLE_ICONS = {"user": "USER", "assistant": "LIGHT_SUN", "tool": "TOOL_SETTINGS", "error": "ERROR", "info": "INFO"}
_TASK_ICONS = {"running": "SORTTIME", "done": "CHECKMARK", "error": "ERROR"}


class FREEPLUGIN_UL_assets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index=0):
        icon = {"hdris": "WORLD", "textures": "TEXTURE", "models": "MESH_MONKEY"}[data.ph_kind]
        layout.label(text=item.name, icon=icon)


class FREEPLUGIN_UL_presets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index=0):
        row = layout.row()
        row.label(text=item.name, icon="ARMATURE_DATA")
        row.label(text=item.sub + (" · in place" if item.in_place else ""))


def _section(layout, panel_id, title, icon, *, closed=False):
    header, body = layout.panel(f"freeplugin_{panel_id}", default_closed=closed)
    header.label(text=title, icon=icon)
    return body


def draw_claude_account(layout):
    """Status of the Claude subscription and the buttons to connect it."""
    info = account.account
    if chat.claude_executable() is None:
        layout.label(text="Claude Code is not installed", icon="ERROR")
        layout.label(text="The chat uses your Claude subscription through it.")
        row = layout.row(align=True)
        row.operator("freeplugin.claude_install", icon="IMPORT")
        row.operator("freeplugin.claude_refresh", text="", icon="FILE_REFRESH")
        return
    if info.login_running:
        layout.label(text="Finish signing in in your browser…", icon="SORTTIME")
        if info.login_url:
            layout.operator("freeplugin.open_url", text="Open the sign-in page again", icon="URL").url = info.login_url
        row = layout.row(align=True)
        row.prop(context_props(), "auth_code", text="Code")
        row.operator("freeplugin.claude_send_code", text="", icon="CHECKMARK")
        layout.label(text="Only paste a code if the page shows one.")
        layout.operator("freeplugin.claude_cancel", icon="CANCEL")
        return
    if info.logged_in:
        layout.label(text=account.label(), icon="CHECKMARK")
        row = layout.row(align=True)
        row.operator("freeplugin.claude_refresh", text="Check again", icon="FILE_REFRESH")
        row.operator("freeplugin.claude_disconnect", icon="X")
        return
    if info.logged_in is None:
        layout.label(text="Checking your Claude sign-in…", icon="SORTTIME")
        return
    layout.label(text="Not connected", icon="ERROR")
    layout.operator("freeplugin.claude_connect", icon="URL")
    layout.label(text="Uses your Claude Pro/Max plan. No API key needed.")
    if info.message:
        layout.label(text=info.message, icon="INFO")


def draw_api_models(layout):
    """The provider's live model list, as menu entries; the current one is checked."""
    current = api_models.current()
    found = api_models.models()
    if not found:
        layout.label(text="Loading the model list…" if api_models.refreshing() else "No list yet", icon="INFO")
    for model_id in found[:40]:
        op = layout.operator("freeplugin.overlay_set", text=model_id,
                             icon="CHECKMARK" if model_id == current else "BLANK1")
        op.target, op.value = "api_model", model_id
    layout.separator()
    layout.operator("freeplugin.api_models_refresh", icon="FILE_REFRESH")


class FREEPLUGIN_MT_api_models(bpy.types.Menu):
    bl_idname = "FREEPLUGIN_MT_api_models"
    bl_label = "Model"

    def draw(self, context):
        draw_api_models(self.layout)


def draw_api_account(layout, settings):
    """Key, model and effort of the API-key chat."""
    info = api_models.preset()
    row = layout.row(align=True)
    row.prop(settings, f"{settings.chat_provider.lower()}_key")
    row.operator("freeplugin.open_url", text="Get a key", icon="URL").url = info["keys_url"]
    if not prefs.api_key():
        layout.label(text=f"Pay per use on your {info['label']} account. No Claude Code needed.", icon="INFO")
        return
    row = layout.row(align=True)
    row.menu(FREEPLUGIN_MT_api_models.bl_idname, text=api_models.current() or "Choose a model")
    row.prop(settings, "chat_effort", text="")
    layout.label(text="Claude's tools here are the built-in Free Plugin tools.", icon="INFO")


def context_props():
    return bpy.context.scene.free_plugin


def _status_header(layout, context):
    box = layout.box()
    row = box.row()
    row.label(text="Free Plugin", icon="PLUGIN")
    row.label(text=f"v{_version()}")
    row.operator("preferences.addon_show", text="", icon="PREFERENCES").module = prefs.ADDON_ID
    column = box.column(align=True)
    if prefs.get().chat_provider != "CLAUDE":
        label = api_models.preset()["label"]
        if prefs.api_key():
            column.label(text=f"Chat: {label} · {api_models.current() or 'choose a model'}", icon="CHECKMARK")
        else:
            column.label(text=f"Chat: {label} key not set", icon="ERROR")
    elif not account.ready():
        column.label(text=account.label(), icon="ERROR")
    else:
        column.label(text=account.label(), icon="CHECKMARK")
    fal = bool(prefs.fal_key())
    column.label(text="fal.ai key: set" if fal else "fal.ai key: not set (Image, 3D, Video)",
                 icon="CHECKMARK" if fal else "DOT")
    if prefs.get().chat_provider != "CLAUDE":
        return  # the API-key chat calls the tools in-process: no MCP to report
    mode = prefs.get().mcp_mode
    if mode != "EXTERNAL":
        from . import mcpserver

        if mcpserver.state.server is not None:
            column.label(text="Free Plugin MCP: on", icon="CHECKMARK")
        else:
            column.label(text=f"Free Plugin MCP: {mcpserver.state.error or 'starting…'}", icon="ERROR")
        if mode == "OWN":
            return
    own = getattr(context.scene, "blendermcp_server_running", None)
    if chat.state.mcp_listening and own is False:
        column.label(text="Blender MCP: used by another Blender", icon="ERROR")
    elif chat.state.mcp_listening:
        column.label(text="Blender MCP: on", icon="CHECKMARK")
    else:
        column.label(text="Blender MCP: off (needed by the chat)", icon="ERROR")


def _version():
    manifest = Path(__file__).with_name("blender_manifest.toml").read_text()
    match = re.search(r'^version = "(.+)"', manifest, re.M)
    return match[1] if match else "?"


def _draw_chat(layout, context):
    props = context.scene.free_plugin
    state = chat.state
    row = layout.row(align=True)
    if prefs.get().chat_provider == "CLAUDE":
        row.prop(prefs.get(), "chat_model", text="")
    else:
        row.menu(FREEPLUGIN_MT_api_models.bl_idname, text=api_models.current() or "Choose a model")
    row.prop(prefs.get(), "chat_effort", text="")
    width = max(24, int((context.region.width - 50) / (7 * context.preferences.system.ui_scale)))
    column = layout.column(align=True)
    shown = state.messages[-10:]
    if len(state.messages) > len(shown):
        column.label(text=f"… {len(state.messages) - len(shown)} earlier messages (Transcript)")
    for message in shown:
        box = column.box().column(align=True)
        lines = []
        for paragraph in message["text"].splitlines() or [""]:
            lines += textwrap.wrap(paragraph, width) or [""]
        limit = 2 if message["role"] == "tool" else 30
        for index, line in enumerate(lines[:limit]):
            box.label(text=line, icon=_ROLE_ICONS.get(message["role"], "DOT") if index == 0 else "BLANK1")
        if len(lines) > limit:
            box.label(text="…", icon="BLANK1")
    if not state.messages:
        column.label(text="Ask Claude to build or change the scene.", icon="INFO")
    if state.usage:
        column.label(text=state.usage, icon="INFO")
    if state.busy:
        row = layout.row()
        row.label(text=state.status or "Working…", icon="SORTTIME")
        row.operator("freeplugin.chat_stop", text="", icon="CANCEL")
    row = layout.row(align=True)
    row.enabled = not state.busy
    row.prop(props, "chat_input", text="", icon="GREASEPENCIL")
    row.operator("freeplugin.chat_send", text="", icon="PLAY")
    row = layout.row(align=True)
    row.operator("freeplugin.chat_transcript", text="Transcript", icon="FILE_TEXT")
    row.operator("freeplugin.chat_reset", text="New", icon="ADD")


def _draw_animation(layout, context):
    props = context.scene.free_plugin
    mesh, rig = animation.character(context.active_object)
    body = _section(layout, "anim_character", "Character", "OUTLINER_OB_ARMATURE")
    if body is not None:
        if mesh is None and rig is None:
            body.label(text="Select the character (mesh or armature)", icon="ERROR")
        elif rig is None:
            body.label(text=f"{mesh.name}: no rig", icon="MESH_DATA")
            body.label(text="A preset rigs it too (Meshy). It must face -Y.", icon="INFO")
        else:
            body.label(text=f"Rig: {rig.name} ({len(rig.data.bones)} bones)", icon="CHECKMARK")
            if rig.animation_data is not None:
                body.prop(rig.animation_data, "action", text="Motion")
    body = _section(layout, "anim_presets", f"Presets ({presets.PRESET_COST})", "ACTION")
    if body is not None:
        row = body.row(align=True)
        row.prop(props, "anim_query", text="", icon="VIEWZOOM")
        row.prop(props, "anim_in_place", text="", icon="PINNED")
        body.prop(props, "anim_category", text="")
        body.template_list("FREEPLUGIN_UL_presets", "", props, "anim_results", props, "anim_index", rows=6)
        body.label(text=f"{len(props.anim_results)} presets")
        body.operator("freeplugin.animate_preset", text=f"Animate  {presets.PRESET_COST}", icon="PLAY")
    body = _section(layout, "anim_motion", f"Motion from text ({presets.MOTION_COST})", "OUTLINER_DATA_GP_LAYER")
    if body is not None:
        body.prop(props, "motion_prompt", text="")
        body.prop(props, "motion_duration")
        if rig is None:
            body.label(text="No rig: a mannequin is created", icon="INFO")
        body.operator("freeplugin.generate_motion", icon="PLAY")
    body = _section(layout, "anim_copy", "Copy a motion (free)", "PASTEDOWN", closed=True)
    if body is not None:
        body.label(text="Select the animated rig, then Ctrl+click", icon="INFO")
        body.label(text="the rig that receives the motion.", icon="BLANK1")
        body.operator("freeplugin.copy_motion", icon="PASTEDOWN")


def _draw_generations(layout):
    body = _section(layout, "generations", "Generations", "RENDERLAYERS")
    if body is None:
        return
    if not tasks.TASKS:
        body.label(text="Nothing generated yet in this session.")
    for task in tasks.TASKS[:8]:
        box = body.box().column(align=True)
        box.label(text=task.label, icon=_TASK_ICONS[task.state])
        box.label(text=task.detail[:80])
        if task.state == "done" and task.label.startswith("Image:") and isinstance(task.result, str):
            _draw_image_actions(box.row(align=True), task.result, labels=True)
    row = body.row(align=True)
    row.operator("freeplugin.open_outputs", text="Open folder", icon="FILE_FOLDER")
    row.operator("freeplugin.clear_tasks", text="Clear", icon="TRASH")


ACTION_ICONS = {"MATERIAL": "MATERIAL", "MESH": "MESH_MONKEY", "SCENE": "SCENE_DATA"}


def _draw_image_actions(row, path, *, labels):
    """Use as material / Make 3D / Build a scene, for one generated image."""
    from .operators import GENERATION_ACTIONS

    for action, label, _text in GENERATION_ACTIONS:
        op = row.operator("freeplugin.use_generation", text=label if labels else "", icon=ACTION_ICONS[action])
        op.filepath, op.action = path, action


LIBRARY_ICONS = {"MESH": "MESH_MONKEY", "ANIMATION": "ARMATURE_DATA", "IMAGE": "IMAGE_DATA", "VIDEO": "FILE_MOVIE"}


def _draw_library(layout, props):
    """Assets › My generations: the files in the output folder, newest first; a click puts one in the scene."""
    body = _section(layout, "library", "My generations", "ASSET_MANAGER")
    if body is None:
        return
    body.prop(props, "lib_filter", expand=True)
    body.prop(props, "lib_query", text="", icon="VIEWZOOM")
    entries = library.CACHE.get(prefs.library_roots(), props.lib_filter, props.lib_query)
    if not entries:
        body.label(text="Nothing yet: what you generate lands here.", icon="INFO")
    column = body.column(align=True)
    for entry in entries[:40]:
        row = column.row(align=True)
        op = row.operator("freeplugin.library_use", text=f"{entry.name}  ·  {entry.label}",
                          icon=LIBRARY_ICONS[entry.kind])
        op.filepath = str(entry.path)
        if entry.kind == "IMAGE":
            _draw_image_actions(row, str(entry.path), labels=False)
    if len(entries) > 40:
        body.label(text=f"+{len(entries) - 40} more: search to narrow down")
    row = body.row(align=True)
    row.label(text=str(prefs.output_root()).replace(str(Path.home()), "~"), icon="FILE_FOLDER")
    row.operator("freeplugin.open_outputs", text="Open", icon="FILEBROWSER")


class FREEPLUGIN_PT_main(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Free Plugin"
    bl_label = "Free Plugin"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.free_plugin
        settings = prefs.get()
        _status_header(layout, context)
        layout.prop(props, "sidebar_tab", expand=True)
        tab = props.sidebar_tab

        if tab == "SCENE":
            if settings.chat_provider == "CLAUDE":
                connected = account.account.logged_in and chat.claude_executable() is not None
                body = _section(layout, "claude", "Claude account", "USER", closed=bool(connected))
                if body is not None:
                    draw_claude_account(body)
                title = "Chat with Claude"
            else:
                body = _section(layout, "api", f"{api_models.preset()['label']} account", "USER",
                                closed=bool(prefs.api_key()))
                if body is not None:
                    draw_api_account(body, settings)
                title = f"Chat with {api_models.preset()['label']}"
            body = _section(layout, "chat", title, "COMMUNITY")
            if body is not None:
                _draw_chat(body, context)
            body = _section(layout, "bar", "Viewport bar", "WINDOW", closed=True)
            if body is not None:
                body.prop(settings, "overlay_enabled", text="Show the prompt bar in the 3D view")
                body.label(text="Click the bar, type, Enter. Shift+Enter: new line, Esc: close.", icon="INFO")

        elif tab == "MESH":
            body = _section(layout, "mesh", "3D Model", "MESH_MONKEY")
            if body is not None:
                body.prop(props, "mesh_source", expand=True)
                provider = (props.mesh_model.entry() or {}).get("provider")
                params.draw_slot(body, context.scene, "mesh", None if provider else
                                 lambda box: ui_controls.draw_settings(box, context.scene, "mesh"))
                entry = props.mesh_model.entry() or {}
                if props.mesh_source == "TEXT":
                    body.prop(props, "mesh_prompt", text="")
                    if entry and not entry.get("text") and not entry.get("provider"):
                        body.label(text="Text → image (Image model) → 3D", icon="INFO")
                elif props.mesh_source == "FILE":
                    body.prop(props, "mesh_image_path", text="")
                if entry.get("provider") == "meshy":
                    row = body.row()
                    row.prop(props, "mesh_texture")
                    sub = row.row()
                    sub.enabled = props.mesh_texture
                    sub.prop(props, "mesh_pbr")
                body.operator("freeplugin.generate_3d", icon="PLAY")
            body = _section(layout, "rig", "Auto-Rig", "ARMATURE_DATA", closed=True)
            if body is not None:
                body.label(text="Rigs the active humanoid (facing -Y)")
                body.prop(props, "rig_provider", text="")
                body.prop(props, "rig_height")
                body.operator("freeplugin.rig", icon="PLAY")
            body = _section(layout, "retexture", "Retexture", "BRUSH_DATA", closed=True)
            if body is not None:
                body.prop(props, "retexture_provider", text="")
                on_fal = props.retexture_provider == "FAL"
                column = body.column()
                column.enabled = bool(prefs.fal_key() if on_fal else prefs.meshy_key())
                if not column.enabled:
                    body.label(text="Needs a fal.ai key" if on_fal else "Needs a Meshy key", icon="INFO")
                column.prop(props, "retexture_prompt", text="Style")
                row = column.row()
                row.prop(props, "retexture_pbr")
                if on_fal:
                    row.prop(props, "retexture_resolution", text="")
                    column.label(text="Price: see fal.ai (Meshy retexture)", icon="INFO")
                column.operator("freeplugin.retexture", icon="PLAY")
            body = _section(layout, "local", "Mesh tools (free)", "MOD_REMESH", closed=True)
            if body is not None:
                row = body.row(align=True)
                row.prop(props, "remesh_voxel")
                row.operator("freeplugin.local_remesh", text="Remesh")
                body.operator("freeplugin.local_lods", icon="MOD_DECIM")

        elif tab == "IMAGE":
            body = _section(layout, "image", "Image", "IMAGE_DATA")
            if body is not None:
                params.draw_slot(body, context.scene, "image",
                                 lambda box: ui_controls.draw_settings(box, context.scene, "image"))
                body.prop(props, "image_prompt", text="")
                body.prop(props, "image_reference")
                if props.image_reference == "FILE":
                    body.prop(props, "image_reference_path", text="")
                body.prop(props, "image_placement")
                body.operator("freeplugin.generate_image", icon="PLAY")
            body = _section(layout, "material", "Material", "MATERIAL", closed=True)
            if body is not None:
                body.label(text="Uses the Image model, on the active mesh", icon="INFO")
                body.prop(props, "texture_prompt", text="")
                body.prop(props, "texture_tiling")
                body.operator("freeplugin.generate_texture", icon="PLAY")

        elif tab == "VIDEO":
            if not settings.show_video:
                layout.label(text="Video is hidden (the most expensive feature).", icon="INFO")
                layout.prop(settings, "show_video", text="Show video")
            else:
                body = _section(layout, "video", "Video", "FILE_MOVIE")
                if body is not None:
                    params.draw_slot(body, context.scene, "video",
                                     lambda box: ui_controls.draw_settings(box, context.scene, "video"))
                    body.prop(props, "video_prompt", text="")
                    body.prop(props, "video_source")
                    body.operator("freeplugin.generate_video", icon="PLAY")

        elif tab == "ANIM":
            _draw_animation(layout, context)

        elif tab == "ASSETS":
            layout.prop(props, "assets_source", expand=True)
            if props.assets_source == "MINE":
                _draw_library(layout, props)
                _draw_generations(layout)
                return
            body = _section(layout, "polyhaven", "Poly Haven (free, CC0)", "WORLD")
            if body is not None:
                body.prop(props, "ph_kind", expand=True)
                row = body.row(align=True)
                row.prop(props, "ph_query", text="", icon="VIEWZOOM")
                row.operator("freeplugin.polyhaven_search", text="", icon="VIEWZOOM")
                body.template_list("FREEPLUGIN_UL_assets", "", props, "ph_results", props, "ph_index", rows=6)
                row = body.row()
                row.prop(props, "ph_resolution", text="")
                row.operator("freeplugin.polyhaven_apply", icon="CHECKMARK")

        _draw_generations(layout)


classes = (
    FREEPLUGIN_MT_api_models,
    FREEPLUGIN_UL_assets,
    FREEPLUGIN_UL_presets,
    FREEPLUGIN_PT_main,
)
