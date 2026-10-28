"""Synthetic humanoid rigs for the retarget and animation tests (built in Blender, nothing on disk).

`smpl()` is a T-pose SMPL skeleton (Hunyuan Motion's naming, hips 1 m high, feet on the
floor) with a short motion; `meshy()` an A-pose skeleton with Meshy's names, 20 % smaller,
with rolled bones and long foot bones, like the rigs importers produce.
Both face -Y; the character's left is +X.
"""

import math

import bpy
from mathutils import Euler, Vector


def _bones(names, scale, a_pose):
    """[(name, head, tail, parent, roll)] for one side-symmetric humanoid."""
    hips, spine, spine2, chest, neck, head = names["center"]
    s = scale
    bones = [
        (hips, (0, 0, 1.0), (0, 0, 1.1), None, 0),
        (spine, (0, 0, 1.1), (0, 0, 1.25), hips, 0),
        (spine2, (0, 0, 1.25), (0, 0, 1.4), spine, 0),
        (chest, (0, 0, 1.4), (0, 0, 1.5), spine2, 0),
        (neck, (0, 0, 1.5), (0, 0, 1.6), chest, 0),
        (head, (0, 0, 1.6), (0, 0, 1.75), neck, 0),
    ]
    drop = math.radians(45) if a_pose else 0.0
    for sign, side in ((1, "L"), (-1, "R")):
        collar, arm, forearm, hand, thigh, shin, foot, toe = names[side]
        shoulder = Vector((0.15 * sign, 0, 1.45))
        along = Vector((math.cos(drop) * sign, 0, -math.sin(drop)))
        elbow, wrist = shoulder + along * 0.3, shoulder + along * 0.55
        roll = math.radians(30) if a_pose else 0
        foot_tail = (0.1 * sign, -0.15, 0.02) if not a_pose else (0.1 * sign, -4.0, 0.02)  # importer-style giant bone
        bones += [
            (collar, (0.03 * sign, 0, 1.45), tuple(shoulder), chest, 0),
            (arm, tuple(shoulder), tuple(elbow), collar, roll),
            (forearm, tuple(elbow), tuple(wrist), arm, roll),
            (hand, tuple(wrist), tuple(wrist + along * 0.1), forearm, roll),
            (thigh, (0.1 * sign, 0, 1.0), (0.1 * sign, 0, 0.55), hips, 0),
            (shin, (0.1 * sign, 0, 0.55), (0.1 * sign, 0, 0.1), thigh, 0),
            (foot, (0.1 * sign, 0, 0.1), foot_tail, shin, 0),
            (toe, (0.1 * sign, -0.1, 0.0), (0.1 * sign, -0.15, 0.0), foot, 0),
        ]
    return [(n, Vector(h) * s, Vector(t) * s, p, r) for n, h, t, p, r in bones]


def build(name, bones, location=(0, 0, 0)):
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    for other in bpy.context.selected_objects:
        other.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name, head, tail, parent, roll in bones:
        bone = data.edit_bones.new(bone_name)
        bone.head, bone.tail, bone.roll = head, tail, roll
        if parent:
            bone.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


SMPL_NAMES = {"center": ("Pelvis", "Spine1", "Spine2", "Spine3", "Neck", "Head"),
              "L": ("L_Collar", "L_Shoulder", "L_Elbow", "L_Wrist", "L_Hip", "L_Knee", "L_Ankle", "L_Foot"),
              "R": ("R_Collar", "R_Shoulder", "R_Elbow", "R_Wrist", "R_Hip", "R_Knee", "R_Ankle", "R_Foot")}
MESHY_NAMES = {"center": ("Hips", "Spine", "Spine01", "Spine02", "neck", "Head"),
               "L": ("LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand", "LeftUpLeg", "LeftLeg", "LeftFoot",
                     "LeftToeBase"),
               "R": ("RightShoulder", "RightArm", "RightForeArm", "RightHand", "RightUpLeg", "RightLeg", "RightFoot",
                     "RightToeBase")}

FRAMES = 10
TRAVEL = 0.5  # metres the source hips move along -Y over the motion


def smpl(name="SMPL", location=(0, 0, 0)):
    return build(name, _bones(SMPL_NAMES, 1.0, False), location)


def meshy(name="Meshy", location=(2, 0, 0)):
    return build(name, _bones(MESHY_NAMES, 0.8, True), location)


def animate(rig, names=SMPL_NAMES):
    """Arms swing down and forward, a knee bends, the hips walk forward."""
    rig.animation_data_create()
    rig.animation_data.action = bpy.data.actions.new(f"{rig.name}Motion")
    hips = rig.pose.bones[names["center"][0]]
    moves = {names["L"][1]: Euler((0.0, 0.6, -0.9)), names["R"][1]: Euler((0.5, 0.0, 0.8)),
             names["L"][2]: Euler((0.0, 0.0, -1.0)), names["R"][4]: Euler((-0.7, 0.0, 0.0)),
             names["R"][5]: Euler((1.0, 0.0, 0.0)), names["center"][1]: Euler((0.2, 0.0, 0.3))}
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
    for frame in (1, FRAMES):
        t = (frame - 1) / (FRAMES - 1)
        for bone_name, euler in moves.items():
            bone = rig.pose.bones[bone_name]
            bone.rotation_quaternion = Euler([a * t for a in euler]).to_quaternion()
            bone.keyframe_insert("rotation_quaternion", frame=frame)
        # Hips' local Y is world +Z here (bone along +Z): travel along world -Y is local +Z.
        hips.location = (0.0, 0.0, TRAVEL * t)
        hips.keyframe_insert("location", frame=frame)
    return rig


def skin(rig, name="Body"):
    """A box mesh bound to every bone, so exporters see a skinned character."""
    bpy.ops.mesh.primitive_cube_add(size=1)
    mesh = bpy.context.active_object
    mesh.name = name
    mesh.scale = (0.4, 0.2, 0.9)
    mesh.location = rig.matrix_world @ Vector((0, 0, 0.9))
    bpy.ops.object.transform_apply(location=False, scale=True, rotation=False)
    group = mesh.vertex_groups.new(name=rig.data.bones[0].name)
    group.add(range(len(mesh.data.vertices)), 1.0, "REPLACE")
    mesh.parent = rig
    mesh.matrix_parent_inverse = rig.matrix_world.inverted()
    mesh.modifiers.new("Armature", "ARMATURE").object = rig
    return mesh
