"""The tools Claude gets from the Free Plugin MCP server (bpy).

Compact on purpose: short descriptions (they are sent to the model every turn) and
short answers (a scene summary is a few lines, not a dump). `run_python` is the
last resort for anything the other tools do not cover.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import math
import tempfile
import time
import traceback
from pathlib import Path

import bpy

from .. import catalog, prefs, presets, tasks
from ..providers import polyhaven
from . import script
from .protocol import Image, Tool, ToolError

on_main = None  # set by the package: runs a function on Blender's main thread and returns its value
call_tool = None  # set by the package: call_tool(name, arguments) runs one tool, as an MCP request would

VECTOR = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
COLOR = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 4,
         "description": "RGB(A), 0-1"}


def _f(value):
    return f"{value:.3g}" if abs(value) >= 1e-4 else "0"


def _vec(values):
    return "(" + ", ".join(_f(v) for v in values) + ")"


def _object(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ToolError(f"No object named {name!r}")
    return obj


def _undo(message):
    with contextlib.suppress(RuntimeError):  # no undo stack in background mode
        bpy.ops.ed.undo_push(message=f"Claude: {message}")


def _line(obj, scene):
    parts = [obj.name, obj.type.lower(), "at " + _vec(obj.location)]
    if obj.type == "MESH":
        parts.append("size " + _vec(obj.dimensions))
        materials = [slot.material.name for slot in obj.material_slots if slot.material]
        if materials:
            parts.append("mat " + ", ".join(materials))
    elif obj.type == "LIGHT":
        parts.append(f"{obj.data.type.lower()} {obj.data.energy:g}W")
    elif obj.type == "CAMERA":
        parts.append(f"{obj.data.lens:g}mm" + (" (active)" if scene.camera == obj else ""))
    if any(abs(r) > 1e-4 for r in obj.rotation_euler):
        parts.append("rot " + _vec(math.degrees(r) for r in obj.rotation_euler) + "°")
    if obj.parent:
        parts.append(f"in {obj.parent.name}")
    if obj.animation_data and obj.animation_data.action:
        parts.append(f"anim {obj.animation_data.action.name}")
    if not obj.visible_get():
        parts.append("hidden")
    return " · ".join(parts)


def scene_summary(limit=60):
    scene = bpy.context.scene
    active = bpy.context.view_layer.objects.active
    selected = [o.name for o in bpy.context.selected_objects]
    lines = [f"Scene {scene.name} · frame {scene.frame_current} ({scene.frame_start}-{scene.frame_end}) · "
             f"{scene.unit_settings.system.lower()} · active: {active.name if active else 'none'} · "
             f"selected: {', '.join(selected) or 'none'} · {len(scene.objects)} objects"]
    objects = sorted(scene.objects, key=lambda o: (o.parent is not None, o.name))
    lines += [_line(obj, scene) for obj in objects[:limit]]
    if len(objects) > limit:
        lines.append(f"… {len(objects) - limit} more (raise limit, or object_info)")
    return "\n".join(lines)


def object_info(name):
    obj = _object(name)
    info = {"name": obj.name, "type": obj.type, "location": list(map(round3, obj.location)),
            "rotation_deg": [round3(math.degrees(r)) for r in obj.rotation_euler],
            "scale": list(map(round3, obj.scale)), "dimensions": list(map(round3, obj.dimensions)),
            "parent": obj.parent.name if obj.parent else None, "children": [c.name for c in obj.children]}
    if obj.type == "MESH":
        info.update(vertices=len(obj.data.vertices), faces=len(obj.data.polygons))
    info["materials"] = [_material_info(slot.material) for slot in obj.material_slots if slot.material]
    info["modifiers"] = [f"{m.name} ({m.type})" for m in obj.modifiers]
    if obj.animation_data and obj.animation_data.action:
        action = obj.animation_data.action
        info["action"] = {"name": action.name, "frames": list(map(round3, action.frame_range))}
    props = {k: v for k, v in obj.items() if isinstance(v, (str, int, float, bool))}
    if props:
        info["custom"] = props
    return info


def round3(value):
    return round(value, 3)


def _principled(material):
    material.use_nodes = True
    return next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def _socket(node, identifier):
    return next((s for s in node.inputs if s.identifier == identifier), None)


def _material_info(material):
    node = _principled(material) if material.use_nodes else None
    if node is None:
        return material.name
    color = _socket(node, "Base Color")
    linked = color is not None and color.is_linked
    return {"name": material.name, "color": "texture" if linked else [round3(c) for c in color.default_value[:3]]}


def _apply_material(obj, name=None, color=None, metallic=None, roughness=None, emission=None,
                    emission_strength=None, alpha=None):
    if obj.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
        raise ToolError(f"{obj.name} is a {obj.type.lower()}: it takes no material")
    material = bpy.data.materials.get(name) if name else (obj.active_material or None)
    if material is None:
        material = bpy.data.materials.new(name or f"{obj.name} material")
    node = _principled(material)
    if node is None:
        raise ToolError(f"{material.name} has no Principled BSDF")
    values = {"Base Color": color, "Metallic": metallic, "Roughness": roughness, "Emission Color": emission,
              "Emission Strength": emission_strength, "Alpha": alpha}
    for identifier, value in values.items():
        if value is None:
            continue
        socket = _socket(node, identifier)
        if socket is None:
            continue
        socket.default_value = (*value[:3], value[3] if len(value) > 3 else 1.0) if isinstance(value, list) else value
    if color is not None:
        material.diffuse_color = (*color[:3], 1.0)  # viewport colour too
    if emission is not None and emission_strength is None:
        _socket(node, "Emission Strength").default_value = 1.0
    if alpha is not None and alpha < 1 and hasattr(material, "surface_render_method"):
        material.surface_render_method = "BLENDED"
    if obj.data.materials:
        if obj.active_material != material:
            obj.data.materials[obj.active_material_index] = material
    else:
        obj.data.materials.append(material)
    return material


PRIMITIVES = {
    "cube": lambda s: bpy.ops.mesh.primitive_cube_add(size=s),
    "sphere": lambda s: bpy.ops.mesh.primitive_uv_sphere_add(radius=s / 2, segments=48, ring_count=24),
    "cylinder": lambda s: bpy.ops.mesh.primitive_cylinder_add(radius=s / 2, depth=s, vertices=48),
    "cone": lambda s: bpy.ops.mesh.primitive_cone_add(radius1=s / 2, depth=s, vertices=48),
    "plane": lambda s: bpy.ops.mesh.primitive_plane_add(size=s),
    "torus": lambda s: bpy.ops.mesh.primitive_torus_add(major_radius=s * 0.375, minor_radius=s * 0.125),
    "monkey": lambda s: bpy.ops.mesh.primitive_monkey_add(size=s),
    "empty": lambda s: bpy.ops.object.empty_add(radius=s / 2),
    "point_light": lambda s: bpy.ops.object.light_add(type="POINT", radius=s / 10),
    "sun_light": lambda s: bpy.ops.object.light_add(type="SUN"),
    "area_light": lambda s: bpy.ops.object.light_add(type="AREA", radius=s),
    "spot_light": lambda s: bpy.ops.object.light_add(type="SPOT"),
    "camera": lambda s: bpy.ops.object.camera_add(),
}


def _transform(obj, location=None, rotation_deg=None, scale=None):
    if location is not None:
        obj.location = location
    if rotation_deg is not None:
        obj.rotation_euler = [math.radians(r) for r in rotation_deg]
    if scale is not None:
        obj.scale = scale


def add_object(kind, name=None, location=None, rotation_deg=None, scale=None, size=1.0, color=None,
               energy=None, parent=None):
    if kind not in PRIMITIVES:
        raise ToolError(f"kind must be one of {', '.join(PRIMITIVES)}")
    PRIMITIVES[kind](size)
    obj = bpy.context.active_object
    if name:
        obj.name = name
        if obj.data is not None:
            obj.data.name = name
    _transform(obj, location, rotation_deg, scale)
    if parent:
        obj.parent = _object(parent)
    if color is not None:
        if obj.type == "LIGHT":
            obj.data.color = color[:3]
        else:
            _apply_material(obj, color=color)
    if energy is not None and obj.type == "LIGHT":
        obj.data.energy = energy
    _undo(f"add {obj.name}")
    return _line(obj, bpy.context.scene)


def edit_object(name, location=None, rotation_deg=None, scale=None, rename=None, parent=None, hide=None,
                select=None, delete=False):
    obj = _object(name)
    if delete:
        bpy.data.objects.remove(obj, do_unlink=True)
        _undo(f"delete {name}")
        return f"Deleted {name}"
    _transform(obj, location, rotation_deg, scale)
    if parent is not None:
        world = obj.matrix_world.copy()
        obj.parent = _object(parent) if parent else None
        obj.matrix_world = world
    if hide is not None:
        obj.hide_set(hide)
        obj.hide_render = hide
    if select:
        for other in bpy.context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    if rename:
        obj.name = rename
    _undo(f"edit {obj.name}")
    return _line(obj, bpy.context.scene)


def set_material(object, material=None, color=None, metallic=None, roughness=None, emission=None,  # noqa: A002
                 emission_strength=None, alpha=None):
    obj = _object(object)
    result = _apply_material(obj, material, color, metallic, roughness, emission, emission_strength, alpha)
    _undo(f"material {result.name}")
    return f"{obj.name}: {_material_info(result)}"


def _view3d():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                return window, area
    return None, None


def _encode(path, max_size):
    image = bpy.data.images.load(str(path))
    try:
        width, height = image.size
        factor = min(1.0, max_size / max(width, height, 1))
        if factor < 1.0:
            image.scale(max(1, int(width * factor)), max(1, int(height * factor)))
        out = Path(tempfile.mkdtemp(prefix="fpb-shot-")) / "shot.png"
        image.filepath_raw, image.file_format = str(out), "PNG"
        image.save()
        return base64.b64encode(out.read_bytes()).decode(), image.size[:]
    finally:
        bpy.data.images.remove(image)


def screenshot(source="viewport", max_size=768):
    if bpy.app.background:
        raise ToolError("Blender runs without a window here: no screenshot")
    path = Path(tempfile.mkdtemp(prefix="fpb-shot-")) / "raw.png"
    if source == "camera":
        from .. import scene as scene_utils

        scene_utils.capture_camera(path)
    else:
        window, area = _view3d()
        if area is None:
            raise ToolError("No 3D view is open")
        region = next(r for r in area.regions if r.type == "WINDOW")
        from .. import overlay

        overlay.state.hidden = True  # the prompt bar would hide part of the scene
        try:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.wm.redraw_timer(type="DRAW", iterations=1)
                bpy.ops.screen.screenshot_area(filepath=str(path))
        finally:
            overlay.state.hidden = False
    data, size = _encode(path, max(64, min(int(max_size), 2048)))
    return f"{source} {size[0]}x{size[1]}", Image(data)


def run_python(code):
    namespace = {"bpy": bpy, "C": bpy.context, "D": bpy.data, "result": None}
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            exec(compile(code, "<claude>", "exec"), namespace)  # noqa: S102 - the point of this tool
    except Exception:  # noqa: BLE001
        lines = traceback.format_exc().splitlines()
        raise ToolError("\n".join([output.getvalue()[-1500:]] + lines[-6:]).strip()) from None
    _undo("python")
    text = output.getvalue()
    if namespace["result"] is not None:
        text += ("\n" if text else "") + f"result = {namespace['result']!r}"
    return text[-4000:] or "ok"


def run_script(code, timeout=300):
    try:
        return script.run(code, call_tool, timeout)
    except script.ScriptError as error:
        raise ToolError(str(error)) from None


# --------------------------------------------------------------------------- tasks (worker thread)

def _start(start):
    """Run start() on the main thread and return the task it queued, or raise its error."""
    before = {t.id for t in tasks.TASKS}

    def run():
        try:
            result = start()
        except RuntimeError as error:  # operator reports and poll failures
            raise ToolError(str(error).replace("Error: ", "").strip()) from None
        if "CANCELLED" in result:
            raise ToolError("Not started (check the arguments and the active object)")
        return next((t for t in tasks.TASKS if t.id not in before), None)

    return on_main(run)


def _wait(task, timeout):
    if task is None:
        return "done"
    end = time.time() + max(0, timeout)
    while task.state == "running" and time.time() < end:
        time.sleep(0.5)
    info = task.as_dict()
    if task.state == "running":
        info["note"] = "still running: call task_status later"
    elif task.state == "error":
        raise ToolError(f"{task.label}: {task.detail}")
    return info


GENERATE_KINDS = ("image", "material", "model3d", "video", "rig", "retexture", "motion", "preset")


def generate(kind, prompt="", model="", options="", object="", preset_id=-1, duration=0.0,  # noqa: A002
             wait=120):
    if kind not in GENERATE_KINDS:
        raise ToolError(f"kind must be one of {', '.join(GENERATE_KINDS)}")
    if options and not isinstance(options, str):
        options = json.dumps(options)

    def start():
        if object:
            target = _object(object)
            for other in bpy.context.selected_objects:
                other.select_set(False)
            target.select_set(True)
            bpy.context.view_layer.objects.active = target
        ops = bpy.ops.freeplugin
        common = {"prompt": prompt, "model": model, "options": options}
        return {
            "image": lambda: ops.generate_image(**common),
            "material": lambda: ops.generate_texture(**common),
            "model3d": lambda: ops.generate_3d(**common),
            "video": lambda: ops.generate_video(**common),
            "rig": lambda: ops.rig(),
            "retexture": lambda: ops.retexture(prompt=prompt),
            "motion": lambda: ops.generate_motion(prompt=prompt, duration=duration),
            "preset": lambda: ops.animate_preset(preset_id=preset_id),
        }[kind]()

    return _wait(_start(start), wait)


def task_status(id=""):  # noqa: A002
    found = [t.as_dict() for t in tasks.TASKS if not id or t.id == id]
    return found or "no task"


def assets(action, kind="hdris", query="", asset_id="", resolution="2k", wait=120):
    if kind not in ("hdris", "textures", "models"):
        raise ToolError("kind must be hdris, textures or models")
    if action == "search":
        hits = polyhaven.search(kind, query)
        return [{"id": asset, "name": name} for asset, name in hits[:15]] or "nothing found"
    if action != "apply" or not asset_id:
        raise ToolError('action is "search", or "apply" with an asset_id')

    def start():
        bpy.context.scene.free_plugin.ph_resolution = resolution
        return bpy.ops.freeplugin.polyhaven_apply(asset_id=asset_id, kind=kind)

    return _wait(_start(start), wait)


def plugin_status():
    def models(slot):
        return {e["key"]: e.get("cost") or "see fal.ai" for e in catalog.models(slot)}

    return {"fal_key": bool(prefs.fal_key()), "meshy_key": bool(prefs.meshy_key()),
            "models": {slot: models(slot) for slot in ("image", "video", "mesh")},
            "animation": {"presets": len(presets.all_presets()), "preset_cost": presets.PRESET_COST,
                          "motion_cost": presets.MOTION_COST},
            "running": [t.label for t in tasks.TASKS if t.state == "running"]}


def find_presets(query="", category="ALL", in_place=False):
    found = presets.search(query, category, in_place)
    return [{"id": p["id"], "name": p["name"], "sub": p["sub"]} for p in found[:20]] or "nothing found"


INSTRUCTIONS = """Tools for the user's open Blender (this window only). Units are metres, Z is up.
Read the scene with scene_summary first. For several steps (many objects, search then apply, generate then
place, waiting on a task), write ONE run_script instead of many calls. run_python (bpy) is the last resort.
generate and assets wait for the result (up to `wait` seconds). Generations are billed to the user's
fal.ai account: say the cost (plugin_status lists prices), prefer free options (modelling, Poly Haven),
never start a video or anything above $0.50 unless the user asked for it."""


def build():
    s, n, b, i = {"type": "string"}, {"type": "number"}, {"type": "boolean"}, {"type": "integer"}
    return [
        Tool("scene_summary", "One line per object: type, location, size, materials, parent, animation.",
             {"limit": i}, run=scene_summary),
        Tool("object_info", "Details of one object (transform, materials, modifiers, mesh, animation).",
             {"name": s}, ["name"], run=object_info),
        Tool("add_object", "Add a primitive, empty, light or camera; optional colour material.",
             {"kind": {"type": "string", "enum": list(PRIMITIVES)}, "name": s, "location": VECTOR,
              "rotation_deg": VECTOR, "scale": VECTOR, "size": {**n, "description": "metres, default 1"},
              "color": COLOR, "energy": {**n, "description": "lights, watts"}, "parent": s},
             ["kind"], run=add_object),
        Tool("edit_object", "Move, rotate, scale, rename, reparent ('' clears), hide, select or delete.",
             {"name": s, "location": VECTOR, "rotation_deg": VECTOR, "scale": VECTOR, "rename": s, "parent": s,
              "hide": b, "select": b, "delete": b}, ["name"], run=edit_object),
        Tool("set_material", "Create or edit the object's Principled material.",
             {"object": s, "material": {**s, "description": "name to reuse or create"}, "color": COLOR,
              "metallic": n, "roughness": n, "emission": COLOR, "emission_strength": n, "alpha": n},
             ["object"], run=set_material),
        Tool("screenshot", "See the 3D viewport or the camera view (PNG).",
             {"source": {"type": "string", "enum": ["viewport", "camera"]}, "max_size": i}, run=screenshot),
        Tool("generate", "Paid fal.ai generation, result put in the scene. image/model3d/video: prompt; "
             "material/retexture: prompt, on `object`; rig/preset/motion: on the character `object` "
             "(preset: preset_id from find_presets; motion: prompt, duration 0.5-12 s).",
             {"kind": {"type": "string", "enum": list(GENERATE_KINDS)}, "prompt": s,
              "model": {**s, "description": "catalog key or fal.ai id"},
              "options": {**s, "description": "model options as JSON"}, "object": s, "preset_id": i,
              "duration": n, "wait": i}, ["kind"], run=generate, main_thread=False),
        Tool("find_presets", "Search the 678 Meshy animation presets (for generate kind=preset).",
             {"query": s, "category": {"type": "string", "enum": [k for k, _ in presets.CATEGORIES]},
              "in_place": b}, run=find_presets, main_thread=False),
        Tool("assets", "Free Poly Haven assets: search, then apply (HDRI → world, texture → active mesh, "
             "model → at the 3D cursor).",
             {"action": {"type": "string", "enum": ["search", "apply"]},
              "kind": {"type": "string", "enum": ["hdris", "textures", "models"]}, "query": s, "asset_id": s,
              "resolution": {"type": "string", "enum": ["1k", "2k", "4k"]}, "wait": i},
             ["action"], run=assets, main_thread=False),
        Tool("task_status", "Background generations (all, or one id).", {"id": s}, run=task_status,
             main_thread=False),
        Tool("plugin_status", "Keys set, model catalog with prices, running tasks.", run=plugin_status),
        Tool("run_python", "Run bpy code in Blender (last resort). print() output and `result` are returned.",
             {"code": s}, ["code"], run=run_python),
        Tool("run_script", script.DESCRIPTION, {"code": s, "timeout": {**i, "description": "seconds, default 300"}},
             ["code"], run=run_script, main_thread=False),
    ]
