"""The simple settings (ratio, resolution, quality, mode…) in the sidebar and the viewport bar.

Choices live on `scene.free_plugin.choices` as one string per control ("auto" by
default). Which choices a model offers comes from `controls.py` and the model's
schema; a control the model cannot take is shown greyed out (sidebar) or hidden (bar).
"""

from __future__ import annotations

import bpy

from . import catalog, controls

# Bar: the controls worth a chip, per bar mode (the sidebar shows them all).
BAR_CONTROLS = {
    "image": ("aspect", "resolution", "quality", "format"),
    "material": ("quality",),
    "mesh": ("mode", "model_type", "topology", "detail"),
    "video": ("duration", "aspect", "resolution", "audio"),
}

_menu_target = {"slot": "image", "key": "aspect"}


def _choices_annotations():
    return {f"{slot}_{control.key}": bpy.props.StringProperty(default=controls.AUTO, name=control.label,
                                                               description=control.description)
            for slot, items in controls.CONTROLS.items() for control in items}


FreePluginChoices = type("FreePluginChoices", (bpy.types.PropertyGroup,),
                         {"__annotations__": _choices_annotations()})


def get_choices(scene, slot) -> dict:
    choices = scene.free_plugin.choices
    return {c.key: getattr(choices, f"{slot}_{c.key}") for c in controls.controls(slot)}


def model_fields(scene, slot):
    """(fields, entry) of the endpoint the slot will call, from the bundled or cached schema."""
    from . import params

    entry, endpoint = params.active_endpoint(scene, slot)
    if entry is None or endpoint is None:
        return {}, entry or {}
    return controls.fields_of(catalog.cached_schema(endpoint)), entry


def control_state(scene, slot, key):
    """(control, supported choices, current value, label to show)."""
    control = next(c for c in controls.controls(slot) if c.key == key)
    fields, entry = model_fields(scene, slot)
    supported = control.choices(fields, entry)
    value = getattr(scene.free_plugin.choices, f"{slot}_{key}")
    label = dict(supported).get(value) if value != controls.AUTO else None
    return control, supported, value, label


def draw_settings(layout, scene, slot, keys=None):
    """A "Settings" block of the sidebar: one row per control, greyed when the model can't take it."""
    header, body = layout.panel(f"freeplugin_settings_{slot}", default_closed=False)
    header.label(text="Settings", icon="PREFERENCES")
    if body is None:
        return
    column = body.column(align=True)
    for control in controls.controls(slot):
        if keys is not None and control.key not in keys:
            continue
        _control, supported, _value, label = control_state(scene, slot, control.key)
        row = column.row(align=True)
        split = row.split(factor=0.4, align=True)
        split.label(text=control.label)
        if supported:
            op = split.operator("freeplugin.control_menu", text=label or "Auto", icon="DOWNARROW_HLT")
            op.slot, op.key = slot, control.key
        else:
            sub = split.row()
            sub.enabled = False
            sub.label(text="not for this model")
    body.label(text="Auto = the model's default", icon="INFO")


class FREEPLUGIN_MT_control(bpy.types.Menu):
    bl_idname = "FREEPLUGIN_MT_control"
    bl_label = "Setting"

    def draw(self, context):
        slot, key = _menu_target["slot"], _menu_target["key"]
        control, supported, value, _label = control_state(context.scene, slot, key)
        layout = self.layout
        layout.label(text=control.label)
        for choice, label in [(controls.AUTO, "Auto (model default)"), *supported]:
            op = layout.operator("freeplugin.control_set", text=label,
                                 icon="CHECKMARK" if choice == value else "BLANK1")
            op.slot, op.key, op.value = slot, key, choice


class FREEPLUGIN_OT_control_menu(bpy.types.Operator):
    bl_idname = "freeplugin.control_menu"
    bl_label = "Choose"
    bl_description = "Change this setting"
    bl_options = {"INTERNAL"}

    slot: bpy.props.StringProperty()
    key: bpy.props.StringProperty()

    def execute(self, context):
        open_menu(self.slot, self.key)
        bpy.ops.wm.call_menu(name=FREEPLUGIN_MT_control.bl_idname)
        return {"FINISHED"}


class FREEPLUGIN_OT_control_set(bpy.types.Operator):
    bl_idname = "freeplugin.control_set"
    bl_label = "Set"
    bl_options = {"INTERNAL"}

    slot: bpy.props.StringProperty()
    key: bpy.props.StringProperty()
    value: bpy.props.StringProperty()

    def execute(self, context):
        setattr(context.scene.free_plugin.choices, f"{self.slot}_{self.key}", self.value)
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        return {"FINISHED"}


def open_menu(slot, key):
    """Point the shared menu at one control (the caller then opens FREEPLUGIN_MT_control)."""
    _menu_target.update(slot=slot, key=key)


classes = (FreePluginChoices, FREEPLUGIN_MT_control, FREEPLUGIN_OT_control_menu, FREEPLUGIN_OT_control_set)
