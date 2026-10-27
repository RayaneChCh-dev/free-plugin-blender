"""Sidebar (N) > Free Plugin."""

from __future__ import annotations

import bpy

from . import params, prefs, tasks


class _Panel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Free Plugin"


class FREEPLUGIN_UL_assets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index=0):
        icon = {"hdris": "WORLD", "textures": "TEXTURE", "models": "MESH_MONKEY"}[data.ph_kind]
        layout.label(text=item.name, icon=icon)


class FREEPLUGIN_PT_main(_Panel):
    bl_label = "Free Plugin"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="fal.ai: " + ("ready" if prefs.fal_key() else "no key"),
                  icon="CHECKMARK" if prefs.fal_key() else "ERROR")
        col.label(text="Meshy: " + ("ready" if prefs.meshy_key() else "optional, no key"),
                  icon="CHECKMARK" if prefs.meshy_key() else "DOT")
        col.label(text="Poly Haven: free", icon="CHECKMARK")
        row = layout.row(align=True)
        row.operator("preferences.addon_show", text="Keys", icon="PREFERENCES").module = prefs.ADDON_ID
        row.operator("freeplugin.open_outputs", text="Outputs", icon="FILE_FOLDER")


class FREEPLUGIN_PT_image(_Panel):
    bl_label = "Image"
    bl_parent_id = "FREEPLUGIN_PT_main"

    def draw(self, context):
        props = context.scene.free_plugin
        layout = self.layout
        params.draw_slot(layout, context.scene, "image")
        layout.prop(props, "image_prompt", text="")
        layout.prop(props, "image_reference")
        if props.image_reference == "FILE":
            layout.prop(props, "image_reference_path", text="")
        layout.prop(props, "image_placement")
        layout.operator("freeplugin.generate_image", icon="IMAGE_DATA")


class FREEPLUGIN_PT_material(_Panel):
    bl_label = "Material"
    bl_parent_id = "FREEPLUGIN_PT_main"

    def draw(self, context):
        props = context.scene.free_plugin
        layout = self.layout
        layout.label(text="Uses the Image panel's model", icon="INFO")
        layout.prop(props, "texture_prompt", text="")
        layout.prop(props, "texture_tiling")
        layout.operator("freeplugin.generate_texture", icon="MATERIAL")


class FREEPLUGIN_PT_video(_Panel):
    bl_label = "Video"
    bl_parent_id = "FREEPLUGIN_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return prefs.get().show_video

    def draw(self, context):
        props = context.scene.free_plugin
        layout = self.layout
        params.draw_slot(layout, context.scene, "video")
        layout.prop(props, "video_prompt", text="")
        layout.prop(props, "video_source")
        layout.operator("freeplugin.generate_video", icon="FILE_MOVIE")


class FREEPLUGIN_PT_model(_Panel):
    bl_label = "3D"
    bl_parent_id = "FREEPLUGIN_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        props = context.scene.free_plugin
        layout = self.layout
        layout.prop(props, "mesh_source", expand=True)
        params.draw_slot(layout, context.scene, "mesh")
        entry = props.mesh_model.entry() or {}
        if props.mesh_source == "TEXT":
            layout.prop(props, "mesh_prompt", text="")
            if entry and not entry.get("text") and not entry.get("provider"):
                layout.label(text="Text → image (Image panel model) → 3D", icon="INFO")
        elif props.mesh_source == "FILE":
            layout.prop(props, "mesh_image_path", text="")
        if entry.get("provider") == "meshy":
            row = layout.row()
            row.prop(props, "mesh_texture")
            sub = row.row()
            sub.enabled = props.mesh_texture
            sub.prop(props, "mesh_pbr")
        layout.operator("freeplugin.generate_3d", icon="MESH_MONKEY")

        layout.separator()
        layout.label(text="Rig the active character")
        layout.prop(props, "rig_provider", text="")
        layout.prop(props, "rig_height")
        layout.operator("freeplugin.rig", icon="ARMATURE_DATA")

        layout.separator()
        layout.label(text="Retexture the active object (Meshy key)")
        col = layout.column()
        col.enabled = bool(prefs.meshy_key())
        col.prop(props, "retexture_prompt", text="Style")
        col.operator("freeplugin.retexture", icon="BRUSH_DATA")


class FREEPLUGIN_PT_polyhaven(_Panel):
    bl_label = "Poly Haven (free)"
    bl_parent_id = "FREEPLUGIN_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        props = context.scene.free_plugin
        layout = self.layout
        layout.prop(props, "ph_kind", expand=True)
        row = layout.row(align=True)
        row.prop(props, "ph_query", text="", icon="VIEWZOOM")
        row.operator("freeplugin.polyhaven_search", text="", icon="VIEWZOOM")
        layout.template_list("FREEPLUGIN_UL_assets", "", props, "ph_results", props, "ph_index", rows=5)
        row = layout.row()
        row.prop(props, "ph_resolution", text="")
        row.operator("freeplugin.polyhaven_apply", icon="CHECKMARK")


class FREEPLUGIN_PT_local(_Panel):
    bl_label = "Local tools (free)"
    bl_parent_id = "FREEPLUGIN_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        props = context.scene.free_plugin
        layout = self.layout
        row = layout.row(align=True)
        row.prop(props, "remesh_voxel")
        row.operator("freeplugin.local_remesh", text="Remesh")
        layout.operator("freeplugin.local_lods", icon="MOD_DECIM")


class FREEPLUGIN_PT_tasks(_Panel):
    bl_label = "Tasks"
    bl_parent_id = "FREEPLUGIN_PT_main"

    def draw(self, context):
        layout = self.layout
        if not tasks.TASKS:
            layout.label(text="Nothing yet")
            return
        icons = {"running": "SORTTIME", "done": "CHECKMARK", "error": "ERROR"}
        for task in tasks.TASKS[:8]:
            box = layout.box().column(align=True)
            box.label(text=task.label, icon=icons[task.state])
            box.label(text=task.detail[:80])
        layout.operator("freeplugin.clear_tasks", icon="TRASH")


classes = (
    FREEPLUGIN_UL_assets,
    FREEPLUGIN_PT_main,
    FREEPLUGIN_PT_image,
    FREEPLUGIN_PT_material,
    FREEPLUGIN_PT_video,
    FREEPLUGIN_PT_model,
    FREEPLUGIN_PT_polyhaven,
    FREEPLUGIN_PT_local,
    FREEPLUGIN_PT_tasks,
)
