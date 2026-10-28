from fpb import rigmap

SMPL = ['Pelvis', 'L_Hip', 'L_Knee', 'L_Ankle', 'L_Foot', 'R_Hip', 'R_Knee', 'R_Ankle', 'R_Foot', 'Spine1', 'Spine2',
        'Spine3', 'Neck', 'Head', 'L_Collar', 'L_Shoulder', 'L_Elbow', 'L_Wrist', 'L_Index1', 'L_Thumb1', 'R_Collar',
        'R_Shoulder', 'R_Elbow', 'R_Wrist', 'R_Index1']
MESHY = ['Hips', 'Spine02', 'Spine01', 'Spine', 'neck', 'Head', 'head_end', 'headfront', 'LeftShoulder', 'LeftArm',
         'LeftForeArm', 'LeftHand', 'RightShoulder', 'RightArm', 'RightForeArm', 'RightHand', 'LeftUpLeg', 'LeftLeg',
         'LeftFoot', 'LeftToeBase', 'RightUpLeg', 'RightLeg', 'RightFoot', 'RightToeBase']
MIXAMO = ["mixamorig:" + n for n in ['Hips', 'Spine', 'Spine1', 'Spine2', 'Neck', 'Head', 'LeftShoulder', 'LeftArm',
                                     'LeftForeArm', 'LeftHand', 'LeftUpLeg', 'LeftLeg', 'LeftFoot', 'LeftToeBase']]
RIGIFY = ['DEF-spine', 'DEF-spine.001', 'DEF-spine.003', 'DEF-spine.005', 'DEF-shoulder.L', 'DEF-upper_arm.L',
          'DEF-forearm.L', 'DEF-hand.L', 'DEF-thigh.L', 'DEF-shin.L', 'DEF-foot.L', 'DEF-toe.L']
UNREAL = ['pelvis', 'spine_01', 'spine_02', 'neck_01', 'head', 'clavicle_l', 'upperarm_l', 'lowerarm_l', 'hand_l',
          'thigh_r', 'calf_r', 'foot_r', 'ball_r']
MESHY_PARENTS = {'Spine': 'Hips', 'Spine01': 'Spine', 'Spine02': 'Spine01', 'neck': 'Spine02'}


def test_sides():
    assert rigmap.side_of("LeftForeArm") == ("L", "ForeArm")
    assert rigmap.side_of("R_Elbow") == ("R", "Elbow")
    assert rigmap.side_of("DEF-upper_arm.L") == ("L", "upper_arm")
    assert rigmap.side_of("clavicle_l") == ("L", "clavicle")
    assert rigmap.side_of("Head")[0] is None


def test_smpl_shoulder_is_the_upper_arm():
    found = rigmap.humanoid_map(SMPL)
    assert found["collar.L"] == "L_Collar" and found["upper_arm.L"] == "L_Shoulder"
    assert found["forearm.L"] == "L_Elbow" and found["hand.L"] == "L_Wrist"
    assert found["thigh.R"] == "R_Hip" and found["shin.R"] == "R_Knee" and found["foot.R"] == "R_Ankle"
    assert found["toe.R"] == "R_Foot" and found["hips"] == "Pelvis"


def test_meshy_shoulder_is_the_collarbone():
    found = rigmap.humanoid_map(MESHY, MESHY_PARENTS)
    assert found["collar.L"] == "LeftShoulder" and found["upper_arm.L"] == "LeftArm"
    assert found["forearm.R"] == "RightForeArm" and found["thigh.L"] == "LeftUpLeg" and found["shin.L"] == "LeftLeg"
    assert found["toe.L"] == "LeftToeBase" and found["head"] == "Head" and found["neck"] == "neck"
    assert found["spine_chain"] == ["Spine", "Spine01", "Spine02"]  # ordered by the hierarchy


def test_other_conventions():
    mixamo = rigmap.humanoid_map(MIXAMO)
    assert mixamo["upper_arm.L"] == "mixamorig:LeftArm" and mixamo["hips"] == "mixamorig:Hips"
    rigify = rigmap.humanoid_map(RIGIFY)
    assert rigify["collar.L"] == "DEF-shoulder.L" and rigify["upper_arm.L"] == "DEF-upper_arm.L"
    assert rigify["shin.L"] == "DEF-shin.L"
    unreal = rigmap.humanoid_map(UNREAL)
    assert unreal["collar.L"] == "clavicle_l" and unreal["forearm.L"] == "lowerarm_l"
    assert unreal["shin.R"] == "calf_r" and unreal["toe.R"] == "ball_r" and unreal["hips"] == "pelvis"


def test_pairs_smpl_to_meshy():
    pairs = dict((t, s) for s, t in rigmap.pairs(SMPL, MESHY, None, MESHY_PARENTS))
    assert pairs["LeftArm"] == "L_Shoulder" and pairs["LeftShoulder"] == "L_Collar"
    assert pairs["RightLeg"] == "R_Knee" and pairs["Hips"] == "Pelvis"
    assert pairs["Spine"] == "Spine1" and pairs["Spine02"] == "Spine3"
    assert "head_end" not in pairs and "headfront" not in pairs
