"""Copy a motion from one humanoid armature to another (main thread, bpy).

Joints are matched by name (`rigmap`). For every frame, each target bone gets the
source bone's rotation relative to its rest pose, after the two rest poses are
aligned: a T-pose motion lands correctly on an A-pose character because each
target bone is first turned to point where its source bone points at rest. The
hips also get the source's displacement, scaled by the ratio of hip heights.
"""

from __future__ import annotations

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import rigmap

MIN_JOINTS = 8


def find_rig(obj):
    """The armature driving obj (itself, its parent, or its Armature modifier), or None."""
    if obj is None:
        return None
    if obj.type == "ARMATURE":
        return obj
    if obj.parent is not None and obj.parent.type == "ARMATURE":
        return obj.parent
    modifier = next((m for m in getattr(obj, "modifiers", ()) if m.type == "ARMATURE" and m.object), None)
    return modifier.object if modifier else None


def _parents(armature):
    return {b.name: (b.parent.name if b.parent else None) for b in armature.data.bones}


def joint_pairs(source, target):
    """[(joint, source bone, target bone, next joint)], each target bone once."""
    found = rigmap.joint_pairs([b.name for b in source.data.bones], [b.name for b in target.data.bones],
                               _parents(source), _parents(target))
    seen, unique = set(), []
    for entry in found:
        if entry[2] not in seen:
            seen.add(entry[2])
            unique.append(entry)
    return unique


def bone_pairs(source, target):
    return [(s, t) for _joint, s, t, _next in joint_pairs(source, target)]


def _head(armature, bone_name):
    return armature.matrix_world @ armature.data.bones[bone_name].head_local


def _rest_world(armature, bone_name):
    return armature.matrix_world @ armature.data.bones[bone_name].matrix_local


def _rest_ground(armature):
    """Lowest bone head of the rest pose, in world units (where the feet stand)."""
    return min((armature.matrix_world @ b.head_local).z for b in armature.data.bones)


def _posed_ground(armature):
    """Lowest bone head of the current pose, in world units."""
    return min((armature.matrix_world @ pb.head).z for pb in armature.pose.bones)


def _depth(bone):
    level = 0
    while bone.parent is not None:
        bone, level = bone.parent, level + 1
    return level


def retarget(source, target, *, action_name="Motion", in_place=False, frame_range=None):
    """Bake source's current action onto target as a new action. Returns (action, matched joints)."""
    if source.animation_data is None or source.animation_data.action is None:
        raise RuntimeError(f"{source.name} has no animation to copy")
    joints = joint_pairs(source, target)
    pairs = [(s, t) for _j, s, t, _n in joints]
    if len(pairs) < MIN_JOINTS:
        raise RuntimeError(f"Only {len(pairs)} joints matched between {source.name} and {target.name}: "
                           "is the target a humanoid rig?")
    scene = bpy.context.scene
    start, end = frame_range or tuple(int(round(f)) for f in source.animation_data.action.frame_range)

    hips = next(((s, t) for s, t in pairs if t == rigmap.humanoid_map(
        [b.name for b in target.data.bones], _parents(target)).get("hips")), None)
    # Root motion is measured from the motion's first frame (a mocap rest pose often stands
    # somewhere else, e.g. hips at the origin and feet below the floor), scaled by hip height.
    ratio, source_start, source_ground, target_ground = 1.0, None, 0.0, _rest_ground(target)
    if hips:
        bpy.context.scene.frame_set(start)
        source_start = (source.matrix_world @ source.pose.bones[hips[0]].matrix).translation.copy()
        source_ground = _posed_ground(source)
        target_hips_height = _rest_world(target, hips[1]).translation.z - target_ground
        source_hips_height = source_start.z - source_ground
        ratio = target_hips_height / source_hips_height if source_hips_height > 1e-6 else 1.0

    # Per pair: rest rotations, and the turn that points the target limb like the source limb at
    # rest. Limb directions come from joint positions (joint → next joint), not from the bones'
    # axes: importers guess bone orientations, so a bone's Y axis need not follow the limb.
    by_joint = {joint: (s, t) for joint, s, t, _n in joints}
    align_of = {}
    for joint, s, t, nxt in joints:
        if nxt in by_joint:
            source_dir = _head(source, by_joint[nxt][0]) - _head(source, s)
            target_dir = _head(target, by_joint[nxt][1]) - _head(target, t)
            if source_dir.length > 1e-6 and target_dir.length > 1e-6:
                align_of[joint] = target_dir.normalized().rotation_difference(source_dir.normalized())
    parent_joint = {"hand": "forearm", "toe": "foot", "head": "neck", "foot": "shin", "neck": "spine"}
    setup = {}
    for joint, s, t, _n in joints:
        align = align_of.get(joint)
        if align is None:  # end joints (hand, toe, head) turn like the limb they hang from
            base, _, side = joint.partition(".")
            fallback = parent_joint.get(base, "")
            fallback = f"{fallback}.{side}" if side else fallback
            align = align_of.get(fallback) or Quaternion()
        source_rest, target_rest = _rest_world(source, s), _rest_world(target, t)
        setup[t] = (s, source_rest.to_quaternion().inverted(), align,
                    target_rest.to_quaternion(), source_rest.translation.copy(), target_rest.translation.copy())

    by_depth: dict[int, list[str]] = {}
    for _s, t in pairs:
        by_depth.setdefault(_depth(target.data.bones[t]), []).append(t)

    if target.animation_data is None:
        target.animation_data_create()
    action = bpy.data.actions.new(action_name)
    action.use_fake_user = True  # kept with the .blend even when another action is active
    target.animation_data.action = action
    for t in setup:
        target.pose.bones[t].rotation_mode = "QUATERNION"

    world_rotation = target.matrix_world.to_quaternion().inverted()
    world_inverse = target.matrix_world.inverted()
    previous: dict[str, Quaternion] = {}
    view_layer = bpy.context.view_layer
    original_frame = scene.frame_current
    try:
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            for level in sorted(by_depth):
                for t in by_depth[level]:
                    s, source_rest_inv, align, target_rest, source_rest_pos, target_rest_pos = setup[t]
                    source_pose = source.matrix_world @ source.pose.bones[s].matrix
                    delta = source_pose.to_quaternion() @ source_rest_inv
                    rotation = world_rotation @ (delta @ align @ target_rest)
                    bone = target.pose.bones[t]
                    current = bone.matrix
                    location = current.translation
                    if hips and t == hips[1]:
                        travel = (source_pose.translation - source_start) * ratio
                        if in_place:
                            travel.x = travel.y = 0.0
                        height = target_ground + (source_pose.translation.z - source_ground) * ratio
                        location = world_inverse @ Vector((target_rest_pos.x + travel.x,
                                                           target_rest_pos.y + travel.y, height))
                    bone.matrix = Matrix.LocRotScale(location, rotation, current.to_scale())
                view_layer.update()
            for t in setup:
                bone = target.pose.bones[t]
                quaternion = bone.rotation_quaternion.copy()
                if t in previous and quaternion.dot(previous[t]) < 0:  # no flips between keys
                    quaternion.negate()
                    bone.rotation_quaternion = quaternion
                previous[t] = quaternion
                bone.keyframe_insert("rotation_quaternion", frame=frame)
                if hips and t == hips[1]:
                    bone.keyframe_insert("location", frame=frame)
    finally:
        scene.frame_set(original_frame)
    return action, len(pairs)


def remove_objects(objects):
    """Delete imported helper objects (and their now-orphan data) after a retarget."""
    for obj in list(objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Armature):
                bpy.data.armatures.remove(data)
