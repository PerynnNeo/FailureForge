"""Headless rigid-body reference experiment for two independently motorized fingers."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

import numpy as np
from pydantic import Field, FiniteFloat

from .contracts import Contract, config_hash


NAMES = ("left_knuckle", "right_knuckle")
KP_NM_PER_RAD = 0.05
KD_NM_S_PER_RAD = 0.004
MAX_TORQUE_NM = 0.05
HAND_MJCF = """<mujoco model="FailureForge two-finger reference hand">
  <compiler angle="radian"/>
  <option timestep="0.001" gravity="0 0 -9.81" integrator="implicitfast"/>
  <default>
    <joint type="hinge" axis="0 0 1" range="-0.6 0.6" limited="true" damping="0.001"/>
    <geom type="capsule" fromto="0 0 0 0 0.07 0" size="0.006" mass="0.05"/>
    <motor ctrllimited="true" ctrlrange="-0.05 0.05"/>
  </default>
  <worldbody>
    <body name="palm">
      <body name="left_finger" pos="-0.055 0 0">
        <joint name="left_knuckle"/><geom/><site name="left_tip" pos="0 0.07 0" size="0.001"/>
      </body>
      <body name="right_finger" pos="0.055 0 0">
        <joint name="right_knuckle"/><geom/><site name="right_tip" pos="0 0.07 0" size="0.001"/>
      </body>
    </body>
  </worldbody>
  <actuator>
    <motor name="left_motor" joint="left_knuckle"/><motor name="right_motor" joint="right_knuckle"/>
  </actuator>
</mujoco>"""


class JointGains(Contract):
    kp: FiniteFloat = Field(gt=0, le=1e8, strict=True)
    kd: FiniteFloat = Field(ge=0, le=1e8, strict=True)
    max_effort: FiniteFloat = Field(gt=0, le=1e6, strict=True)


class PDController(Contract):
    schema_version: Literal["joint-pd-v1"]
    joints: dict[str, JointGains] = Field(min_length=1, max_length=64)
    bias_compensation: bool = Field(default=False, strict=True)


def _load_controller(blob):
    if not blob or len(blob) > 65536:
        raise ValueError("A declarative joint PD controller must be a JSON file of up to 64 KiB")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate controller key: {key}")
            result[key] = value
        return result
    try:
        return PDController.model_validate(json.loads(blob.decode("utf-8-sig"), object_pairs_hook=unique))
    except RecursionError as exc:
        raise ValueError("Controller JSON exceeds the supported nesting depth") from exc


class Drives:
    """Explicit joint-to-position, velocity and actuator mapping in public-name order."""

    def __init__(self, model, names, effort):
        self.names = names
        joints = [model.joint(name) for name in names]
        self.q = np.array([joint.qposadr[0] for joint in joints])
        self.v = np.array([joint.dofadr[0] for joint in joints])
        self.motor = np.array([np.flatnonzero(model.actuator_trnid[:, 0] == joint.id).item() for joint in joints])
        self.limits = np.array([joint.range for joint in joints])
        self.effort = effort


def _simulate(mujoco, model, drives, profile, start, target, duration, samples):
    substeps = max(1, math.ceil(duration / ((samples - 1) * 0.001)))
    model.opt.timestep = duration / ((samples - 1) * substeps)
    data = mujoco.MjData(model)
    data.qpos[drives.q] = start
    mujoco.mj_forward(model, data)
    names = drives.names
    kp, kd, max_force = (np.array([getattr(profile.joints[n], key) for n in names]) for key in ("kp", "kd", "max_effort"))
    times = np.zeros(samples)
    positions = np.zeros((samples, len(names)))
    velocities = np.zeros_like(positions)
    controls = np.zeros_like(positions)
    positions[0] = start
    peak_speed, peak_force = np.zeros(len(names)), np.zeros(len(names))
    max_excursion = np.zeros(len(names))
    within_limits = True
    max_contacts = int(data.ncon)
    for sample in range(1, samples):
        for _ in range(substeps):
            mujoco.mj_step1(model, data)
            command = kp * (target - data.qpos[drives.q]) - kd * data.qvel[drives.v]
            if profile.bias_compensation:
                command += data.qfrc_bias[drives.v]
            data.ctrl[drives.motor] = np.clip(command, -max_force, max_force)
            peak_force = np.maximum(peak_force, np.abs(data.ctrl[drives.motor]))
            max_contacts = max(max_contacts, int(data.ncon))
            mujoco.mj_step2(model, data)
            q = data.qpos[drives.q]
            max_excursion = np.maximum(max_excursion, np.abs(q - start))
            peak_speed = np.maximum(peak_speed, np.abs(data.qvel[drives.v]))
            within_limits = within_limits and bool(np.all((q >= drives.limits[:, 0] - 1e-9) & (q <= drives.limits[:, 1] + 1e-9)))
        times[sample] = data.time
        positions[sample] = data.qpos[drives.q]
        velocities[sample] = data.qvel[drives.v]
        controls[sample] = data.ctrl[drives.motor]
    if (not np.isfinite(positions).all() or not np.isfinite(peak_speed).all() or
            any(warning.number for warning in data.warning) or not math.isclose(data.time, duration, abs_tol=1e-8)):
        raise ValueError("MuJoCo reported an unstable integration or did not reach the declared time")
    mujoco.mj_forward(model, data)
    measured = {"within_joint_limits": within_limits, "peak_contact_count": max_contacts,
                "max_joint_excursion": dict(zip(names, max_excursion.tolist())),
                "peak_generalized_force": dict(zip(names, peak_force.tolist())), "timestep_s": float(model.opt.timestep),
                "integration_steps": substeps * (samples - 1), "sampled_joint_velocity": dict(zip(names, velocities.T.tolist())),
                "sampled_generalized_force": dict(zip(names, controls.T.tolist()))}
    return times, positions, peak_speed, measured, data


def dynamic_motion(request, robot_xml, root, by_child, tip, start, targets, controller_bytes):
    try:
        import mujoco
    except ImportError as exc:
        raise ValueError("Dynamic tracking requires MuJoCo 3.8.1 in the solver environment") from exc
    if mujoco.__version__ != "3.8.1":
        raise ValueError(f"Dynamic tracking requires MuJoCo 3.8.1; installed {mujoco.__version__}")
    reference = request.model_asset_id is None
    names = list(start)
    initial = np.array([start[n] for n in names])
    if reference:
        mjcf, efforts = HAND_MJCF, dict.fromkeys(names, MAX_TORQUE_NM)
    else:
        from .urdf_mjcf import primitive_mjcf
        mjcf, efforts = primitive_mjcf(robot_xml, root, by_child, tip)
    model = mujoco.MjModel.from_xml_string(mjcf)
    drives = Drives(model, names, efforts)
    supplied = _load_controller(controller_bytes) if controller_bytes is not None else None
    if reference:
        default_gains = {n: JointGains(kp=KP_NM_PER_RAD, kd=KD_NM_S_PER_RAD, max_effort=MAX_TORQUE_NM) for n in names}
        baseline = PDController(schema_version="joint-pd-v1", joints=default_gains)
    elif supplied is None:
        initial_data = mujoco.MjData(model)
        initial_data.qpos[drives.q] = initial
        mujoco.mj_forward(model, initial_data)
        mass = np.zeros((model.nv, model.nv))
        mujoco.mj_fullM(model, mass, initial_data.qM)
        natural_rate = request.gain_per_s
        default_gains = {n: JointGains(kp=mass[i, i] * natural_rate**2, kd=2 * mass[i, i] * natural_rate,
                                      max_effort=efforts[n]) for n, i in zip(names, drives.v)}
        baseline = PDController(schema_version="joint-pd-v1", joints=default_gains, bias_compensation=True)
    else:
        baseline = supplied
    selected = supplied or baseline
    if set(selected.joints) != set(names):
        raise ValueError("Controller joint map must cover exactly the movable model joints")
    if any(selected.joints[n].max_effort > efforts[n] for n in names):
        raise ValueError("Controller max_effort exceeds an actuator effort limit")
    qualification = []
    home = np.zeros(len(names)) if reference else initial
    qualification_tasks = [("hold_open" if reference else "hold_initial", baseline, home, home)]
    if reference:
        qualification_tasks.append(("close_to_reference", baseline, home, np.array([-0.35, 0.35])))
        if supplied is not None:
            qualification_tasks.append(("controller_hold_initial", selected, initial, initial))
    max_speeds = np.array([next(j.velocity for j in by_child.values() if j.name == n) for n in names])
    for task, profile, pose, target in qualification_tasks:
        _, q, speed, measured, state = _simulate(mujoco, model, drives, profile, pose, target, 1.0, 21)
        error = float(np.max(np.abs(q[-1] - target)))
        hold = task != "close_to_reference"
        assessed_error = max(measured["max_joint_excursion"].values()) if hold else error
        check = {"task": task, "duration_s": 1, "max_joint_error": error, "target": dict(zip(names, target.tolist())),
                 "joint_error_tolerance": 0.01, "assessed_joint_error": assessed_error,
                 "controller_sha256": config_hash(profile.model_dump()),
                 "passed": bool(assessed_error <= 0.01 and measured["within_joint_limits"] and np.all(speed <= max_speeds))}
        if reference and task != "controller_hold_initial":
            expected_gap = 0.11 - 0.14 * math.sin(float(target[1]))
            gap = float(np.linalg.norm(state.site("left_tip").xpos - state.site("right_tip").xpos))
            check["tip_gap_error_m"] = abs(gap - expected_gap)
            check["passed"] = check["passed"] and check["tip_gap_error_m"] <= 0.001
        qualification.append(check)
    if reference and not all(check["passed"] for check in qualification[:2]):
        raise ValueError("Reference hand qualification failed its joint or fingertip criteria")
    times, positions, peak, measured, state = _simulate(mujoco, model, drives, selected, initial,
                                np.array([targets[n] for n in names]), request.duration_s, request.samples)
    if reference:
        measured["final_tip_separation_m"] = float(np.linalg.norm(state.site("left_tip").xpos - state.site("right_tip").xpos))
        measured["peak_torque_nm"] = measured["peak_generalized_force"]
    else:
        measured["final_tip_xyz_m"] = state.site("tracked_tip").xpos.tolist()
    profile = selected.model_dump()
    measured.update({"simulator": "MuJoCo", "version": mujoco.__version__, "reference_qualification": qualification,
                     "mjcf_sha256": hashlib.sha256(mjcf.encode()).hexdigest(), "controller": "torque_pd",
                     "controller_asset_id": request.controller_asset_id, "controller_profile": profile,
                     "controller_sha256": config_hash(profile),
                     "controller_file_sha256": hashlib.sha256(controller_bytes).hexdigest() if controller_bytes is not None else None,
                     "force_units": "N for prismatic joints; N m for revolute joints",
                     "collision_model": "Primitive collision geometries, MuJoCo default contact filtering and friction."})
    return times, {name: positions[:, i] for i, name in enumerate(names)}, dict(zip(names, peak.tolist())), measured
