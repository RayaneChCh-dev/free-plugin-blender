"""Model choice and schema-driven options: one slot property group per panel.

A slot holds the chosen model and a collection of `FreePluginParam`, one per
field of that model's fal.ai schema. Only values the user touched (or that the
catalog pre-sets) are sent; everything else keeps the model's own default.
"""

from __future__ import annotations

import json

import bpy

from . import catalog, tasks

_KINDS = [(k, k.title(), "") for k in ("STRING", "INT", "FLOAT", "BOOL", "ENUM")]
_enum_cache: dict[str, list] = {}
_model_items_cache: dict[str, list] = {}


def _mark_changed(self, context):
    self.changed = True


def _enum_items(self, context):
    # Blender keeps only a pointer to the returned list: hold it here.
    if self.options not in _enum_cache:
        values = json.loads(self.options or "[]")
        _enum_cache[self.options] = [(str(v), str(v), "") for v in values] or [("NONE", "-", "")]
    return _enum_cache[self.options]


class FreePluginParam(bpy.types.PropertyGroup):
    title: bpy.props.StringProperty()
    kind: bpy.props.EnumProperty(items=_KINDS)
    description: bpy.props.StringProperty()
    options: bpy.props.StringProperty()
    minimum: bpy.props.FloatProperty(default=-1e30)
    maximum: bpy.props.FloatProperty(default=1e30)
    changed: bpy.props.BoolProperty()
    s: bpy.props.StringProperty(update=_mark_changed)
    i: bpy.props.IntProperty(update=_mark_changed)
    f: bpy.props.FloatProperty(update=_mark_changed)
    b: bpy.props.BoolProperty(update=_mark_changed)
    e: bpy.props.EnumProperty(items=_enum_items, update=_mark_changed)

    def value(self):
        if self.kind == "ENUM":
            values = json.loads(self.options or "[]")
            return next((v for v in values if str(v) == self.e), self.e)
        if self.kind == "INT":
            return int(min(max(self.i, self.minimum), self.maximum))
        if self.kind == "FLOAT":
            return float(min(max(self.f, self.minimum), self.maximum))
        return {"STRING": self.s, "BOOL": self.b}[self.kind]

    def set_value(self, value):
        if self.kind == "ENUM":
            if str(value) in {item[0] for item in _enum_items(self, None)}:
                self.e = str(value)
        elif self.kind == "INT":
            self.i = int(value)
        elif self.kind == "FLOAT":
            self.f = float(value)
        elif self.kind == "BOOL":
            self.b = bool(value)
        else:
            self.s = str(value)


def _model_changed(self, context):
    if context is not None and context.scene is not None:
        sync_scene(context.scene)


class _SlotMixin:
    SLOT = ""
    custom_id: bpy.props.StringProperty(name="fal.ai model id", description="e.g. fal-ai/flux/dev")
    params: bpy.props.CollectionProperty(type=FreePluginParam)
    loaded: bpy.props.StringProperty()
    status: bpy.props.StringProperty()

    def entry(self) -> dict | None:
        if self.model == catalog.CUSTOM:
            return catalog.custom_entry(self.custom_id.strip()) if self.custom_id.strip() else None
        return catalog.get(self.SLOT, self.model)

    def payload(self) -> dict:
        return {p.name: p.value() for p in self.params if p.changed}


def _slot_class(slot_name):
    def items(self, context):
        # Blender keeps only a pointer to the returned list: hold it here.
        _model_items_cache[slot_name] = [
            *((e["key"], e["label"], e.get("cost", "")) for e in catalog.models(slot_name)),
            (catalog.CUSTOM, "Other fal.ai model…", "Paste any model id from fal.ai/models"),
        ]
        return _model_items_cache[slot_name]

    return type(
        f"FreePlugin{slot_name.title()}Slot",
        (_SlotMixin, bpy.types.PropertyGroup),
        {"SLOT": slot_name,
         "__annotations__": {"model": bpy.props.EnumProperty(name="Model", items=items, update=_model_changed)}},
    )


SLOT_CLASSES = {name: _slot_class(name) for name in catalog.SLOTS}


def _uses_image(scene, slot_name) -> bool:
    props = scene.free_plugin
    return {
        "image": props.image_reference != "NONE",
        "video": props.video_source != "TEXT",
        "mesh": props.mesh_source != "TEXT",
    }[slot_name]


def active_endpoint(scene, slot_name) -> tuple[dict | None, str | None]:
    slot = getattr(scene.free_plugin, f"{slot_name}_model")
    entry = slot.entry()
    if entry is None:
        return None, None
    return entry, catalog.endpoint(entry, _uses_image(scene, slot_name))


def rebuild(slot, schema: dict | None, defaults: dict):
    kept = {p.name: p.value() for p in slot.params if p.changed}
    slot.params.clear()
    for field in (schema or {}).get("fields", []):
        param = slot.params.add()
        param.name, param.title, param.kind = field["name"], field["title"], field["kind"]
        param.description = field.get("description", "")
        param.options = json.dumps(field.get("options", []))
        param.minimum = field.get("minimum", -1e30)
        param.maximum = field.get("maximum", 1e30)
        if "default" in field:
            param.set_value(field["default"])
        param.changed = False
        for source in (defaults, kept):
            if field["name"] in source:
                param.set_value(source[field["name"]])
                param.changed = True
    slot.loaded = (schema or {}).get("id", "")
    slot.status = ""


def sync_slot(scene, slot_name, *, force=False):
    slot = getattr(scene.free_plugin, f"{slot_name}_model")
    entry, endpoint_id = active_endpoint(scene, slot_name)
    if entry is None or endpoint_id is None:
        if slot.params or slot.loaded:
            slot.params.clear()
            slot.loaded = ""
        return
    if slot.loaded == endpoint_id and not force:
        return
    schema = None if force else catalog.cached_schema(endpoint_id)
    if schema is not None:
        rebuild(slot, schema, entry.get("defaults", {}))
        return
    slot.status = "loading options…"
    scene_name, defaults = scene.name, entry.get("defaults", {})

    def done(task, schema):
        target = bpy.data.scenes.get(scene_name)
        if target is not None:
            rebuild(getattr(target.free_plugin, f"{slot_name}_model"), schema, defaults)
        return f"{len(schema['fields'])} options"

    def failed_guard(task):
        try:
            return catalog.fetch_schema(endpoint_id)
        except Exception:
            target = bpy.data.scenes.get(scene_name)
            if target is not None:
                getattr(target.free_plugin, f"{slot_name}_model").status = "could not load this model"
            raise

    tasks.run(f"Options: {endpoint_id}", failed_guard, done)


def sync_scene(scene):
    for slot_name in catalog.SLOTS:
        sync_slot(scene, slot_name)


def draw_slot(layout, scene, slot_name, before_advanced=None):
    slot = getattr(scene.free_plugin, f"{slot_name}_model")
    layout.prop(slot, "model", text="")
    if slot.model == catalog.CUSTOM:
        row = layout.row(align=True)
        row.prop(slot, "custom_id", text="")
        row.operator("freeplugin.load_model", text="Load", icon="FILE_REFRESH").slot = slot_name
        if not slot.loaded:
            layout.label(text="Paste an id from fal.ai/models, then Load", icon="INFO")
    entry, endpoint_id = active_endpoint(scene, slot_name)
    if entry and entry.get("cost"):
        layout.label(text=f"Price: {entry['cost']}", icon="INFO")
    if entry and not entry.get("provider") and endpoint_id is None:
        layout.label(text="This model needs an input image", icon="ERROR")
    if slot.status:
        layout.label(text=slot.status, icon="SORTTIME")
    if before_advanced is not None:
        before_advanced(layout)
    if not slot.params:
        return
    header, body = layout.panel(f"freeplugin_{slot_name}_options", default_closed=True)
    header.label(text=f"Advanced ({len(slot.params)})")
    if body is None:
        return
    column = body.column()
    for param in slot.params:
        attr = {"STRING": "s", "INT": "i", "FLOAT": "f", "BOOL": "b", "ENUM": "e"}[param.kind]
        row = column.row()
        row.prop(param, attr, text=param.title)
        if param.changed:
            row.label(text="", icon="DOT")


def _sync_all_scenes(*_args):
    for scene in bpy.data.scenes:
        if hasattr(scene, "free_plugin"):
            sync_scene(scene)


@bpy.app.handlers.persistent
def _on_load(_dummy):
    bpy.app.timers.register(_sync_all_scenes, first_interval=0.2)


classes = (FreePluginParam, *SLOT_CLASSES.values())


def register_handlers():
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_sync_all_scenes, first_interval=0.5)


def unregister_handlers():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
