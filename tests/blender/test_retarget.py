"""Retarget a T-pose SMPL motion onto a smaller A-pose Meshy rig built in the test."""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import harness  # noqa: E402
import rigs  # noqa: E402

LIMBS = (("L_Shoulder", "L_Elbow", "LeftArm", "LeftForeArm"), ("L_Elbow", "L_Wrist", "LeftForeArm", "LeftHand"),
         ("R_Shoulder", "R_Elbow", "RightArm", "RightForeArm"), ("R_Hip", "R_Knee", "RightUpLeg", "RightLeg"),
         ("R_Knee", "R_Ankle", "RightLeg", "RightFoot"), ("L_Hip", "L_Knee", "LeftUpLeg", "LeftLeg"),
         ("Spine1", "Spine2", "Spine", "Spine01"))


def head(rig, bone):
    return rig.matrix_world @ rig.pose.bones[bone].head


def worst_angle(source, target, frame):
    bpy.context.scene.frame_set(frame)
    angles = []
    for s0, s1, t0, t1 in LIMBS:
        a, b = head(source, s1) - head(source, s0), head(target, t1) - head(target, t0)
        angles.append(a.angle(b))
    return max(angles) * 57.2958


def ground(rig):
    return min((rig.matrix_world @ b.head).z for b in rig.pose.bones)


def test():
    retarget = harness.enable()(".retarget")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    source = rigs.animate(rigs.smpl())
    target = rigs.meshy()

    before = worst_angle(source, target, rigs.FRAMES)
    harness.check("control: limbs differ before the retarget", before > 20.0, f"{before:.1f}°")
    pairs = retarget.joint_pairs(source, target)
    harness.check("joints matched", len(pairs) >= 20, len(pairs))
    action, joints = retarget.retarget(source, target, action_name="Wave")
    harness.check("new action, kept with the file", action.name == "Wave" and action.use_fake_user
                  and target.animation_data.action == action)
    harness.check("frame range copied", tuple(round(f) for f in action.frame_range) == (1, rigs.FRAMES),
                  tuple(action.frame_range))
    for frame in (1, 5, rigs.FRAMES):
        angle = worst_angle(source, target, frame)
        harness.check(f"limb directions match at frame {frame}", angle < 2.0, f"{angle:.2f}°")

    rest_ground = min((target.matrix_world @ b.head_local).z for b in target.data.bones)
    bpy.context.scene.frame_set(1)
    harness.check("feet on the ground", abs(ground(target) - rest_ground) < 0.01, ground(target) - rest_ground)
    start_s, start_t = head(source, "Pelvis").copy(), head(target, "Hips").copy()
    bpy.context.scene.frame_set(rigs.FRAMES)
    travel_s, travel_t = head(source, "Pelvis") - start_s, head(target, "Hips") - start_t
    harness.check("source walks", travel_s.length > 0.3, travel_s)
    harness.check("travel scaled by hip height", (travel_t - travel_s * 0.8).length < 0.01, (travel_s, travel_t))

    retarget.retarget(source, target, action_name="Wave in place", in_place=True)
    bpy.context.scene.frame_set(1)
    start = head(target, "Hips").copy()
    bpy.context.scene.frame_set(rigs.FRAMES)
    moved = head(target, "Hips") - start
    harness.check("in place: no travel on the floor", abs(moved.x) < 1e-3 and abs(moved.y) < 1e-3, moved)
    harness.check("both actions kept", {"Wave", "Wave in place"} <= set(bpy.data.actions.keys()))

    tiny = rigs.build("Tiny", [("Root", (0, 0, 0), (0, 0, 1), None, 0)])
    try:
        retarget.retarget(source, tiny)
        harness.check("non-humanoid target refused", False)
    except RuntimeError as error:
        harness.check("non-humanoid target refused", "joints matched" in str(error), error)


harness.run(test)
