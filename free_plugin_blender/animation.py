"""Animation tab: Meshy presets, motion from text, and copying a motion between rigs.

    bpy.ops.freeplugin.animate_preset(preset_id=106)          # a preset from data/animations.json
    bpy.ops.freeplugin.generate_motion(prompt="a joyful jump", duration=3)
    bpy.ops.freeplugin.copy_motion()                           # selected rig → active rig

The character is the active object (a mesh, or its armature). When it already has a
rig, every new motion is retargeted onto that rig as a new action named after it;
otherwise a preset imports Meshy's rigged character in place of the mesh, and a
motion from text keeps the imported mannequin.
"""

from __future__ import annotations

import bpy
from mathutils import Vector

from . import net, prefs, presets, retarget, scene, tasks
from . import props as props_module
from .operators import _stamp
from .providers import fal

CHARACTER_TAG = "free_plugin_character"  # on an armature imported for a mesh: the mesh's name


def character(obj):
    """(mesh, rig) of the character the active object belongs to; either may be None."""
    rig = retarget.find_rig(obj)
    if obj is not None and obj.type == "MESH":
        return obj, rig
    if rig is None:
        return None, None
    meshes = [c for c in rig.children_recursive if c.type == "MESH"]
    return max(meshes, key=lambda m: len(m.data.vertices), default=None), rig


def _height(obj):
    heights = [(obj.matrix_world @ Vector(corner)).z for corner in obj.bound_box]
    return max(heights) - min(heights)


def _feet(obj):
    """Centre of the bounding box at its lowest point, in world units."""
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    centre = sum(corners, Vector()) / len(corners)
    return Vector((centre.x, centre.y, min(c.z for c in corners)))


def _export_mesh(mesh):
    """The mesh alone (rest shape, no skin, no animation) as a GLB for Meshy."""
    for other in bpy.context.selected_objects:
        other.select_set(False)
    hidden = mesh.hide_get()
    mesh.hide_set(False)
    mesh.select_set(True)
    path = prefs.output_dir("exports") / _stamp(mesh.name, "glb")
    try:
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True,
                                  export_skins=False, export_animations=False)
    finally:
        mesh.select_set(False)
        mesh.hide_set(hidden)
    return path


def _imported(names):
    objects = [bpy.data.objects[n] for n in names if n in bpy.data.objects]
    armature = next((o for o in objects if o.type == "ARMATURE" and o.animation_data
                     and o.animation_data.action), None)
    if armature is None:
        retarget.remove_objects(objects)
        raise RuntimeError("The downloaded file has no animated skeleton")
    return objects, armature


def _fit_timeline(action):
    current = bpy.context.scene
    current.frame_end = max(current.frame_end, int(round(action.frame_range[1])))


def _onto_rig(objects, source, rig, name):
    """Retarget the imported motion onto rig, then delete what was imported."""
    imported = source.animation_data.action
    try:
        action, joints = retarget.retarget(source, rig, action_name=name)
    finally:
        retarget.remove_objects(objects)
        if imported.users == 0:
            bpy.data.actions.remove(imported)
        _make_active(rig)  # the import selected what was just deleted
    _fit_timeline(action)
    return action, joints


def _make_active(obj):
    for other in bpy.context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _keep(objects, armature, name, at):
    """Keep an imported character: its action renamed, roots moved to `at`, made active."""
    action = armature.animation_data.action
    action.name, action.use_fake_user = name, True
    for obj in objects:
        if obj.parent is None:
            obj.location = at
    _make_active(armature)
    _fit_timeline(action)
    return action


class FREEPLUGIN_OT_animate_preset(bpy.types.Operator):
    bl_idname = "freeplugin.animate_preset"
    bl_label = "Animate"
    bl_description = (f"Apply a Meshy animation preset to the active character, {presets.PRESET_COST} on fal.ai. "
                      "Without a rig, the character is rigged too. It must face -Y in Blender")
    bl_options = {"REGISTER"}

    preset_id: bpy.props.IntProperty(name="Preset", default=-1, options={"SKIP_SAVE"},
                                     description="Id from the animation library; -1: the one picked in the list")

    @classmethod
    def poll(cls, context):
        return character(context.active_object)[0] is not None

    def execute(self, context):
        props = context.scene.free_plugin
        preset_id = self.preset_id
        if preset_id < 0 and 0 <= props.anim_index < len(props.anim_results):
            preset_id = props.anim_results[props.anim_index].preset_id
        preset = presets.get(preset_id)
        if preset is None:
            self.report({"ERROR"}, "Pick a preset in the list first")
            return {"CANCELLED"}
        mesh, rig = character(context.active_object)
        rig_name, mesh_name = rig.name if rig else None, mesh.name
        payload = {"height_meters": round(max(0.1, _height(mesh)), 3), "enable_animation": True,
                   "animation_action_id": preset_id}
        glb, key, folder = _export_mesh(mesh), prefs.fal_key(), prefs.output_dir("animations")
        name = preset["name"]

        def work(task):
            result = fal.run(fal.RIG_MODEL, {"model_url": net.data_uri(glb, "application/octet-stream"), **payload},
                             key, task.set)
            task.set("downloading…")
            return net.download(fal.animation_url(result), folder / _stamp(f"{mesh_name}-{name}", "glb"))

        def done(task, path):
            objects, source = _imported(scene.import_glb(path))
            target = bpy.data.objects.get(rig_name) if rig_name else None
            if target is not None:
                action, joints = _onto_rig(objects, source, target, name)
                return f"{action.name} on {target.name} ({joints} joints)"
            original = bpy.data.objects.get(mesh_name)
            at = _feet(original) if original else bpy.context.scene.cursor.location.copy()
            if original is not None:
                original.hide_set(True)
                original.hide_render = True
            source[CHARACTER_TAG] = mesh_name
            action = _keep(objects, source, name, at)
            return f"{action.name} on {source.name} (new rig)"

        tasks.run(f"Animate: {name[:40]}", work, done)
        return {"FINISHED"}


class FREEPLUGIN_OT_generate_motion(bpy.types.Operator):
    bl_idname = "freeplugin.generate_motion"
    bl_label = "Generate motion"
    bl_description = (f"Text → motion with Hunyuan Motion, {presets.MOTION_COST} on fal.ai, retargeted onto the "
                      "active character's rig (or kept as a mannequin when there is none)")
    bl_options = {"REGISTER"}

    prompt: bpy.props.StringProperty(name="Prompt", options={"SKIP_SAVE"})
    duration: bpy.props.FloatProperty(name="Duration", default=0.0, min=0.0, max=12.0, options={"SKIP_SAVE"},
                                      description="Seconds (0.5 to 12); 0: the panel's value")

    def execute(self, context):
        props = context.scene.free_plugin
        prompt = (self.prompt or props.motion_prompt).strip()
        if not prompt:
            self.report({"ERROR"}, "Describe the motion first")
            return {"CANCELLED"}
        duration = min(12.0, max(0.5, self.duration or props.motion_duration))
        rig = character(context.active_object)[1]
        rig_name = rig.name if rig else None
        key, folder = prefs.fal_key(), prefs.output_dir("animations")
        cursor = context.scene.cursor.location.copy()

        def work(task):
            result = fal.run(fal.MOTION_MODEL, {"prompt": prompt, "duration": duration, "output_format": "fbx"},
                             key, task.set)
            task.set("downloading…")
            return net.download(fal.motion_url(result), folder / _stamp(prompt, "fbx"))

        def done(task, path):
            objects, source = _imported(scene.import_glb(path))
            name = prompt[:60]
            target = bpy.data.objects.get(rig_name) if rig_name else None
            if target is not None:
                action, joints = _onto_rig(objects, source, target, name)
                return f"{action.name} on {target.name} ({joints} joints)"
            action = _keep(objects, source, name, cursor)
            return f"{action.name} on {source.name} (mannequin)"

        tasks.run(f"Motion: {prompt[:40]}", work, done)
        return {"FINISHED"}


def _copy_pair(context):
    """(source, target): the active armature receives the motion of the other selected one."""
    target = context.active_object
    if target is None or target.type != "ARMATURE":
        return None, target
    source = next((o for o in context.selected_objects if o is not target and o.type == "ARMATURE"
                   and o.animation_data and o.animation_data.action), None)
    return source, target


class FREEPLUGIN_OT_copy_motion(bpy.types.Operator):
    bl_idname = "freeplugin.copy_motion"
    bl_label = "Copy motion"
    bl_description = ("Copy the motion of the selected armature onto the active one (free, runs in Blender). "
                      "Select the source, then Ctrl+click the target")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _copy_pair(context)[0] is not None

    def execute(self, context):
        source, target = _copy_pair(context)
        try:
            action, joints = retarget.retarget(source, target, action_name=source.animation_data.action.name)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        _fit_timeline(action)
        self.report({"INFO"}, f"{action.name} on {target.name} ({joints} joints)")
        return {"FINISHED"}


def _fill_presets(*_args):
    for scene_ in bpy.data.scenes:
        props = getattr(scene_, "free_plugin", None)
        if props is not None and not props.anim_results:
            props_module.refresh_presets(props)


@bpy.app.handlers.persistent
def _on_load(_dummy):
    bpy.app.timers.register(_fill_presets, first_interval=0.2)


classes = (FREEPLUGIN_OT_animate_preset, FREEPLUGIN_OT_generate_motion, FREEPLUGIN_OT_copy_motion)


def register():
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_fill_presets, first_interval=0.5)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if bpy.app.timers.is_registered(_fill_presets):
        bpy.app.timers.unregister(_fill_presets)
