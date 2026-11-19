import hashlib
import math
from pathlib import Path

import pytest

from failureforge.project_robot import HAND_TARGET, RobotRunRequest, robot_reference, run_robot


ARM = b"""<robot name="test linkage">
  <link name="base"/><link name="carriage"/><link name="arm"/><link name="tool"/>
  <joint name="slide" type="prismatic"><parent link="base"/><child link="carriage"/>
    <origin xyz="1 0 0" rpy="0 0 1.5707963267948966"/><axis xyz="1 0 0"/><limit lower="0" upper="2" velocity="2"/></joint>
  <joint name="hinge" type="revolute"><parent link="carriage"/><child link="arm"/>
    <axis xyz="0 0 1"/><limit lower="-2" upper="2" velocity="2"/></joint>
  <joint name="offset" type="fixed"><parent link="arm"/><child link="tool"/><origin xyz="1 0 0"/></joint>
</robot>"""

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
SLIDE = (CONFIGS / "vertical-slide.urdf").read_bytes()
PROFILE = (CONFIGS / "vertical-slide-controller.json").read_bytes()
OMX = (CONFIGS.parent / "examples/openmanipulator-x/open_manipulator_x.urdf").read_bytes()


def test_prescribed_motion_reconstructs_link_frames_and_mixed_units():
    request = RobotRunRequest(model_asset_id="asset", targets={"slide": 1, "hinge": math.pi / 2}, samples=3)
    result = run_robot(request, ARM)
    assert result["passed"]
    assert result["model"]["urdf_sha256"] == hashlib.sha256(ARM).hexdigest()
    assert result["trajectory"]["time_s"] == [0, 1, 2]
    assert result["trajectory"]["tip_xyz_m"][0] == pytest.approx([1, 1, 0])
    assert result["trajectory"]["tip_xyz_m"][-1] == pytest.approx([0, 1, 0])
    assert result["trajectory"]["joint_positions"]["slide"] == [0, 0.5, 1]
    assert result["metrics"]["peak_joint_speed"]["hinge"] == pytest.approx(math.pi / 4)
    assert [joint["unit"] for joint in result["model"]["joints"]] == ["m", "rad"]


def test_manufacturer_urdf_coupled_gripper_and_tip():
    request = RobotRunRequest(model_asset_id="omx", targets={"joint1": 0.35, "gripper_left_joint": 0.005},
                              tip_link="end_effector_link")
    result = run_robot(request, OMX)
    q = result["trajectory"]["joint_positions"]
    assert result["passed"] and q["gripper_right_joint"] == q["gripper_left_joint"]
    assert result["metrics"]["tip_displacement_m"] > 0.05
    # Check a non-identity multiplier/offset and the follower limit gate.
    modified = OMX.replace(b'multiplier="1"', b'multiplier="-2" offset="0.001"')
    assert run_robot(request, modified)["trajectory"]["joint_positions"]["gripper_right_joint"][-1] == pytest.approx(-0.009)
    with pytest.raises(ValueError, match="initial and target"):
        run_robot(request, OMX.replace(b'multiplier="1"', b'multiplier="-10"'))
    with pytest.raises(ValueError, match="mimic commanded"):
        run_robot(RobotRunRequest(model_asset_id="omx", targets={"gripper_right_joint": 0}, tip_link="link5"), OMX)
    with pytest.raises(ValueError, match="independent movable"):
        run_robot(RobotRunRequest(model_asset_id="omx", mode="mujoco_pd", targets={"joint1": 0.1}, tip_link="link5"), OMX)


def test_velocity_servo_matches_saturated_then_exponential_solution():
    request = RobotRunRequest(model_asset_id="asset", targets={"slide": 2}, mode="velocity_servo",
                              gain_per_s=2, samples=5, duration_s=2)
    result = run_robot(request, ARM)
    position = result["trajectory"]["joint_positions"]["slide"]
    assert position[1] == pytest.approx(1)
    assert position[-1] == pytest.approx(2 - math.exp(-3))
    assert result["metrics"]["peak_joint_speed"]["slide"] == 2
    assert result["metrics"]["within_velocity_limits"]
    assert not result["passed"]


def test_calibrated_joint_parameter_binds_and_reproduces_first_order_step():
    from failureforge.project_bindings import resolve_bindings
    from failureforge.project_runs import ProjectTest
    check = ProjectTest(label="Pivot step", adapter="robot_motion", inputs={
        "mode": "velocity_servo", "targets": {"left_knuckle": 0.2}, "duration_s": 0.4, "samples": 5},
        bindings={"time_constant_s": "Instrumented joint time constant"})
    parameter = {"name": "Instrumented joint time constant", "unit": "ms", "value": "100", "source": "calibrated",
                 "range_min": None, "range_max": None, "evidence": "held-out log analysis"}
    inputs, evidence = resolve_bindings(check, {"revision": 3, "analysis_type": "robot_behavior", "parameters": [parameter]})
    request = RobotRunRequest.model_validate(inputs)
    assert RobotRunRequest.model_validate(request.model_dump()) == request
    assert evidence["time_constant_s"]["resolved_value"] == pytest.approx(.1)
    result = run_robot(request)
    t = result["trajectory"]["time_s"]
    q = result["trajectory"]["joint_positions"]
    assert q["left_knuckle"] == pytest.approx([.2 * (1 - math.exp(-s/.1)) for s in t])
    assert q["right_knuckle"] == [0] * 5
    assert result["criteria"]["servo_response"] == {"joint": "left_knuckle", "time_constant_s": .1, "effective_gain_per_s": 10}
    assert result["passed"]


def test_fast_joint_response_still_obeys_the_urdf_velocity_limit():
    request = RobotRunRequest(mode="velocity_servo", targets={"left_knuckle": .2}, time_constant_s=.005,
                              duration_s=.04, samples=5)
    result = run_robot(request)
    assert result["trajectory"]["joint_positions"]["left_knuckle"][1] == pytest.approx(.08)
    assert result["metrics"]["peak_joint_speed"]["left_knuckle"] == 8


@pytest.mark.parametrize("changes", [
    {"gain_per_s": 3.0}, {"mode": "prescribed"}, {"mode": "mujoco_pd"},
    {"targets": HAND_TARGET}, {"time_constant_s": 0.0}, {"time_constant_s": float("nan")}
])
def test_time_constant_accepts_only_one_velocity_servo_target_and_one_parameterization(changes):
    with pytest.raises(ValueError):
        RobotRunRequest.model_validate({"mode": "velocity_servo", "targets": {"left_knuckle": .2}, "time_constant_s": .1, **changes})


def test_rotational_calibration_cannot_be_applied_to_an_uploaded_prismatic_joint():
    with pytest.raises(ValueError, match="rotational joint"):
        run_robot(RobotRunRequest(model_asset_id="model", mode="velocity_servo", targets={"slide": .1}, time_constant_s=.12), ARM)


def test_prescribed_velocity_violation_is_a_failed_experiment():
    result = run_robot(RobotRunRequest(model_asset_id="id", targets={"slide": 2}, duration_s=0.5), ARM)
    assert result["metrics"]["target_reached"]
    assert not result["metrics"]["within_velocity_limits"]
    assert not result["passed"]


@pytest.mark.parametrize("data,targets,match", [
    (ARM.replace(b'type="revolute"', b'type="floating"'), {"slide": 1}, "bounded revolute"),
    (ARM.replace(b'<axis xyz="0 0 1"/>', b'<axis xyz="0 0 0"/>'), {"slide": 1}, "axis"),
    (ARM.replace(b'<parent link="carriage"/>', b'<parent link="tool"/>'), {"slide": 1}, "cycle"),
    (ARM.replace(b'lower="-2"', b'lower="nan"'), {"slide": 1}, "finite"),
    (ARM.replace(b'<parent link="carriage"/>', b'<mimic joint="slide"/><parent link="carriage"/>'), {"slide": 1}, "same joint type"),
    (b'<!DOCTYPE robot>' + ARM, {"slide": 1}, "document types"),
    (ARM, {"hinge": 3}, "initial and target"),
    (ARM, {"offset": 0}, "Unknown or fixed"),
])
def test_invalid_model_or_joint_map_is_a_setup_error(data, targets, match):
    with pytest.raises(ValueError, match=match):
        run_robot(RobotRunRequest(model_asset_id="asset", targets=targets), data)


def test_asset_bytes_must_match_selection():
    with pytest.raises(ValueError, match="model bytes"):
        run_robot(RobotRunRequest(targets=HAND_TARGET), ARM)
    with pytest.raises(ValueError, match="model bytes"):
        run_robot(RobotRunRequest(model_asset_id="id", targets={"slide": 1}))
    with pytest.raises(ValueError, match="controller asset"):
        run_robot(RobotRunRequest(mode="mujoco_pd", targets=HAND_TARGET, controller_asset_id="gains"))
    with pytest.raises(ValueError, match="torque controller"):
        run_robot(RobotRunRequest(targets=HAND_TARGET, controller_asset_id="gains"), controller_bytes=b"{}")


def test_dynamic_reference_and_feedback_from_nonzero_state():
    pytest.importorskip("mujoco")
    reference = robot_reference()
    result = run_robot(RobotRunRequest(**reference["example"]))
    assert result["passed"] and result["dynamics"]["simulator"] == "MuJoCo"
    assert result["dynamics"]["mjcf_sha256"] == reference["mjcf_sha256"]
    assert [check["task"] for check in result["dynamics"]["reference_qualification"]] == ["hold_open", "close_to_reference"]
    assert all(check["passed"] for check in result["dynamics"]["reference_qualification"])
    expected_gap = 0.11 - 0.14 * math.sin(0.35)
    assert result["dynamics"]["final_tip_separation_m"] == pytest.approx(expected_gap, abs=0.001)
    assert result["metrics"]["tip_displacement_m"] > 0.02
    assert result["dynamics"]["integration_steps"] >= 2000
    assert 0 < max(result["dynamics"]["peak_torque_nm"].values()) <= 0.05
    assert result["trajectory"]["time_s"][-1] == pytest.approx(2)
    # Short budget from an opposite pose gives an actual failed target check.
    short = run_robot(RobotRunRequest(mode="mujoco_pd", targets=HAND_TARGET, duration_s=0.01,
                                     initial={"left_knuckle": 0.3, "right_knuckle": -0.3}))
    assert not short["passed"] and short["dynamics"]["reference_qualification"][1]["passed"]
    assert short["trajectory"]["joint_positions"]["left_knuckle"][0] == 0.3


def test_imported_dynamic_controller_tracks_the_analytic_gravity_compensated_slide():
    pytest.importorskip("mujoco")
    request = RobotRunRequest(model_asset_id="asset_slide", controller_asset_id="asset_pd", targets={"lift": 0.15},
                              mode="mujoco_pd", duration_s=2, samples=101, tolerance=0.001)
    blob = PROFILE
    result = run_robot(request, SLIDE, blob)
    dynamics = result["dynamics"]
    assert result["passed"] and result["adapter"] == "urdf-primitive-pd-v1"
    assert dynamics["reference_qualification"][0]["passed"]
    assert dynamics["controller_asset_id"] == "asset_pd"
    assert dynamics["controller_file_sha256"] == hashlib.sha256(blob).hexdigest()
    # A 1 kg slide under f = 25*(goal-q) - 10*v + m*g is critically damped at 5/s.
    t = result["trajectory"]["time_s"][20]
    expected_q = 0.15 * (1 - (1 + 5 * t) * math.exp(-5 * t))
    assert result["trajectory"]["joint_positions"]["lift"][20] == pytest.approx(expected_q, abs=0.0005)
    assert dynamics["final_tip_xyz_m"] == pytest.approx(result["trajectory"]["tip_xyz_m"][-1])
    assert dynamics["peak_generalized_force"]["lift"] == pytest.approx(9.81 + 25 * 0.15, abs=1e-6)
    assert dynamics["sampled_generalized_force"]["lift"][-1] == pytest.approx(9.81, abs=0.01)


def test_default_imported_controller_and_insufficient_lift_actuator():
    pytest.importorskip("mujoco")
    request = RobotRunRequest(model_asset_id="model", targets={"lift": 0.1}, mode="mujoco_pd")
    good = run_robot(request, SLIDE)
    assert good["passed"] and good["dynamics"]["controller_asset_id"] is None
    assert good["dynamics"]["controller_profile"]["joints"]["lift"]["kp"] == pytest.approx(9.0)
    weak = run_robot(request, SLIDE.replace(b'effort="30"', b'effort="1"'))
    assert weak["passed"] is None
    assert not weak["dynamics"]["reference_qualification"][0]["passed"]
    assert weak["dynamics"]["peak_generalized_force"]["lift"] <= 1


def test_rebased_copy_of_trajectory_cannot_serve_as_heldout_evidence():
    from failureforge.project_inputs import JointResponse, fit_joint_response
    spec = JointResponse(joint_name="pivot", hardware_revision="fixture",
                         training_asset_id="asset_" + "0" * 32, validation_asset_id="asset_" + "1" * 32,
                         max_validation_rmse_rad=0.02)
    def log(epoch):
        lines = ["time_s,command_rad,position_rad"]
        lines.extend(f"{epoch + t},0.5,{q}" for t, q in [(0, 0), (.12, .15), (.3, .3), (.45, .42)])
        return "\n".join(lines).encode()
    with pytest.raises(ValueError, match="duplicates"):
        fit_joint_response(spec, log(0), log(1700000000))


@pytest.mark.parametrize("model,expected", [
    (SLIDE.replace(b'<sphere radius="0.05"/>', b'<mesh filename="package://external/shape"/>'), "primitive|box"),
    (SLIDE.replace(b'ixx="0.001"', b'ixx="1000"'), "inertia"),
    (SLIDE.replace(b'<mass value="1"/>', b'<mass value="0"/>'), "mass"),
    (SLIDE.replace(b'effort="30"', b'effort="0"'), "effort"),
    (SLIDE.replace(b'</robot>', b'<gazebo><plugin filename="external"/></gazebo></robot>'), "extensions"),
])
def test_physics_import_rejects_unsupported_models(model, expected):
    pytest.importorskip("mujoco")
    with pytest.raises(ValueError, match=expected):
        run_robot(RobotRunRequest(model_asset_id="model", targets={"lift": 0.1}, mode="mujoco_pd"), model)


@pytest.mark.parametrize("controller,expected", [
    (b'{"schema_version":"joint-pd-v1","joints":{"unknown":{"kp":5,"kd":0,"max_effort":1}}}', "joint map"),
    (b'{"schema_version":"joint-pd-v1","joints":{"lift":{"kp":5,"kd":0,"max_effort":31}}}', "effort limit"),
    (b'{"schema_version":"joint-pd-v1","joints":{},"joints":{}}', "Duplicate"),
    (b'{"schema_version":"uploaded-plugin","source":"example.py"}', "validation"),
])
def test_controller_schema_and_limits(controller, expected):
    pytest.importorskip("mujoco")
    request = RobotRunRequest(model_asset_id="model", controller_asset_id="gains", targets={"lift": 0.1}, mode="mujoco_pd")
    with pytest.raises(ValueError, match=expected):
        run_robot(request, SLIDE, controller)
