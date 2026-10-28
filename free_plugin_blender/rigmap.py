"""Find the humanoid joints of a skeleton from its bone names. No bpy.

Rigs name the same joint differently: SMPL (`L_Shoulder` is the upper arm), Mixamo
and Meshy (`LeftShoulder` is the collarbone, `LeftArm` the upper arm), Rigify
(`upper_arm.L`), Unreal-style (`upperarm_l`)… `humanoid_map()` returns
{canonical joint: bone name} so a motion can be carried from one rig to another.
"""

from __future__ import annotations

import re

SIDES = ("L", "R")
LIMBS = ("collar", "upper_arm", "forearm", "hand", "thigh", "shin", "foot", "toe")
JOINTS = ("hips", "spine", "neck", "head") + tuple(f"{limb}.{side}" for side in SIDES for limb in LIMBS)

# Per limb, word patterns tried in order on the side-stripped, lower-case name.
# Order matters: "upperarm" must win over "arm", "forearm" over "arm".
_LIMB_PATTERNS = {
    "collar": (r"^(collar|clavicle|clav)$",),
    "forearm": (r"^(forearm|lowerarm|lower_arm|elbow)$",),
    "upper_arm": (r"^(upperarm|upper_arm|arm)$",),
    "hand": (r"^(hand|wrist)$",),
    "thigh": (r"^(thigh|upleg|upperleg|upper_leg|hip)$",),
    "shin": (r"^(shin|calf|knee|lowerleg|lower_leg|leg)$",),
    "foot": (r"^(foot|ankle)$",),
    "toe": (r"^(toe|toebase|toes|ball|foot_end)$",),
}
_PREFIX = re.compile(r"^(mixamorig\d*:|def-|org-|mch-|bip\d*[ _]|[a-z0-9]+:)", re.I)


def _clean(name: str) -> str:
    return _PREFIX.sub("", name).strip()


def side_of(name: str):
    """("L"|"R"|None, name without its side marker), e.g. "LeftForeArm" → ("L", "ForeArm")."""
    base = _clean(name)
    match = re.match(r"^(left|right)(?=[A-Z_.\- ])", base) or re.match(r"^(left|right)", base, re.I)
    if match:
        return ("L" if match.group(1).lower() == "left" else "R"), base[match.end():].lstrip("_.- ")
    match = re.match(r"^([LR])[_.\- ]", base)
    if match:
        return match.group(1), base[2:]
    match = re.search(r"[_.\- ]([LRlr])$", base)
    if match:
        return match.group(1).upper(), base[:match.start()]
    match = re.search(r"(Left|Right)$", base)
    if match:
        return ("L" if match.group(1) == "Left" else "R"), base[:match.start()]
    return None, base


def _word(name: str) -> str:
    """Lower-case, digits and a trailing "1" of SMPL-style chains removed: "ForeArm" → "forearm"."""
    return re.sub(r"[\d]+$", "", name.replace(" ", "")).lower().strip("_.-")


def _family_is_smpl(names) -> bool:
    """SMPL / SMPL-H skeletons (Hunyuan Motion, many mocap tools): L_Hip, L_Knee, L_Collar…"""
    smpl_names = sum(bool(re.match(r"^[lr]_(collar|hip|knee|ankle|shoulder|elbow|wrist)$", _clean(n).lower()))
                     for n in names)
    return smpl_names >= 4


def humanoid_map(names, parents=None) -> dict:
    """{joint: bone name} for the joints found. `parents` ({bone: parent}) orders the spine."""
    names = list(names)
    smpl = _family_is_smpl(names)
    found: dict[str, str] = {}

    for name in names:
        word = _word(_clean(name))
        if "hips" not in found and word in ("hips", "hip", "pelvis") and side_of(name)[0] is None:
            found["hips"] = name
        elif "neck" not in found and word in ("neck",):
            found["neck"] = name
        elif "head" not in found and word == "head":
            found["head"] = name

    for name in names:
        side, base = side_of(name)
        if side is None:
            continue
        word = _word(base)
        # Words whose meaning depends on the convention.
        if word == "shoulder":  # collarbone, except SMPL where it is the upper arm
            limbs = ("upper_arm",) if smpl else ("collar",)
        elif word == "foot" and smpl:  # SMPL: ankle = foot, foot = toes
            limbs = ("toe",)
        else:
            limbs = ("collar", "forearm", "upper_arm", "hand", "thigh", "shin", "foot", "toe")
        for limb in limbs:
            key = f"{limb}.{side}"
            if key not in found and (word == "shoulder" or any(re.match(p, word) for p in _LIMB_PATTERNS[limb])
                                     or (word == "foot" and smpl)):
                found[key] = name
                break

    spine = [n for n in names if re.match(r"^(spine|chest|upperchest|upper_chest|torso)", _word(_clean(n)))
             and side_of(n)[0] is None]
    if spine:
        if parents:
            def depth(bone):
                level = 0
                while parents.get(bone):
                    bone, level = parents[bone], level + 1
                return level
            spine.sort(key=depth)
        found["spine"] = spine[0]
        found["spine_chain"] = spine  # the whole chain, lowest first
    return found


# The joint each limb points to: a limb's direction is the line from its joint to this one.
NEXT_JOINT = {
    "collar": "upper_arm", "upper_arm": "forearm", "forearm": "hand",
    "thigh": "shin", "shin": "foot", "foot": "toe", "neck": "head",
}


def joint_pairs(source_names, target_names, source_parents=None, target_parents=None):
    """[(joint, source bone, target bone, next joint or None)] for the joints both rigs have.

    Spine bones are named "spine0", "spine1"… along the target's chain and matched end to
    end with the source's chain; the last one points to the neck, the hips to "spine0".
    """
    source = humanoid_map(source_names, source_parents)
    target = humanoid_map(target_names, target_parents)
    result = []
    source_chain, target_chain = source.get("spine_chain", []), target.get("spine_chain", [])
    for index, bone in enumerate(target_chain if source_chain else []):
        position = index / max(1, len(target_chain) - 1)
        nxt = f"spine{index + 1}" if index + 1 < len(target_chain) else "neck"
        result.append((f"spine{index}", source_chain[round(position * (len(source_chain) - 1))], bone, nxt))
    for joint in JOINTS:
        if joint == "spine" or joint not in source or joint not in target:
            continue
        base, _, side = joint.partition(".")
        nxt = "spine0" if joint == "hips" else NEXT_JOINT.get(base)
        result.append((joint, source[joint], target[joint], f"{nxt}.{side}" if nxt and side else nxt))
    return result


def pairs(source_names, target_names, source_parents=None, target_parents=None):
    """[(source bone, target bone)] for the joints both rigs have."""
    return [(s, t) for _j, s, t, _n in joint_pairs(source_names, target_names, source_parents, target_parents)]
