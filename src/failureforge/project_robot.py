"""Bounded URDF kinematics and a self-contained two-finger reference mechanism."""
from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Annotated, Literal

import numpy as np
from pydantic import Field, FiniteFloat, model_validator
from scipy.spatial.transform import Rotation

from .contracts import Contract


JointName = Annotated[str, Field(min_length=1, max_length=100)]
JointMap = dict[JointName, Annotated[FiniteFloat, Field(strict=True)]]


class RobotRunRequest(Contract):
    model_asset_id: str | None = Field(default=None, min_length=1, max_length=128)
    controller_asset_id: str | None = Field(default=None, min_length=1, max_length=128)
    mode: Literal["prescribed", "velocity_servo", "mujoco_pd"] = "prescribed"
    targets: JointMap = Field(min_length=1, max_length=64)
    initial: JointMap = Field(default_factory=dict, max_length=64)
    duration_s: FiniteFloat = Field(default=2, ge=0.01, le=20, strict=True)
    samples: int = Field(default=41, ge=2, le=241, strict=True)
    tip_link: JointName | None = None
    time_constant_s: FiniteFloat | None = Field(default=None, ge=0.001, le=1000, strict=True,
        description="First-order response time of a single commanded rotational joint in velocity_servo mode (seconds).")
    gain_per_s: FiniteFloat | None = Field(
        default_factory=lambda data: 3.0 if data.get("time_constant_s") is None else None,
        gt=0, le=50, strict=True)
    tolerance: FiniteFloat = Field(default=0.01, gt=0, le=1, strict=True)

    @model_validator(mode="after")
    def servo_parameter(self):
        if self.time_constant_s is None:
            if self.gain_per_s is None:
                raise ValueError("Supply a numerical gain_per_s or omit it for the default gain of 3/s")
        elif self.gain_per_s is not None:
            raise ValueError("Choose either time_constant_s or gain_per_s for a servo run")
        elif self.mode != "velocity_servo" or len(self.targets) != 1:
            raise ValueError("time_constant_s requires velocity_servo mode and exactly one commanded joint")
        return self


def _reference_urdf():
    fingers = []
    for side, x in (("left", -0.055), ("right", 0.055)):
        fingers.append(f"""
          <link name="{side}_finger"/><link name="{side}_tip"/>
          <joint name="{side}_knuckle" type="revolute"><parent link="palm"/><child link="{side}_finger"/>
            <origin xyz="{x} 0 0"/><axis xyz="0 0 1"/><limit lower="-0.60" upper="0.60" velocity="8" effort="0.05"/></joint>
          <joint name="{side}_distal" type="fixed"><parent link="{side}_finger"/><child link="{side}_tip"/>
            <origin xyz="0 0.07 0"/></joint>""")
    return ('<robot name="FailureForge two-finger hand"><link name="palm"/>' + "".join(fingers) + "</robot>").encode()


HAND_URDF = _reference_urdf()
HAND_TARGET = {"left_knuckle": -0.35, "right_knuckle": 0.35}


def robot_reference():
    from .robot_dynamics import HAND_MJCF
    return {"id": "two_finger_hand_v1", "name": "Two-finger reference hand", "version": "1.0",
            "source": "Original FailureForge reference geometry", "license": "MIT",
            "urdf_sha256": hashlib.sha256(HAND_URDF).hexdigest(),
            "mjcf_sha256": hashlib.sha256(HAND_MJCF.encode()).hexdigest(),
            "modes": ["prescribed", "velocity_servo", "mujoco_pd"],
            "targets": dict(HAND_TARGET), "tip_link": "left_tip",
            "example": RobotRunRequest(mode="mujoco_pd", targets=HAND_TARGET, tip_link="left_tip").model_dump(),
            "task": "Track two finger joint setpoints on a fixed palm without an object."}


@dataclass
class Joint:
    name: str
    kind: str
    parent: str
    child: str
    origin: np.ndarray
    axis: np.ndarray
    lower: float
    upper: float
    velocity: float
    mimic: tuple[str, float, float] | None


def _child(node, tag, required=False):
    matches = node.findall(tag)
    if len(matches) > 1 or (required and not matches):
        raise ValueError(f"Expected one {tag} element in {node.get('name', node.tag)}")
    return matches[0] if matches else None


def _numbers(text, count):
    parts = (text or "").split()
    if len(parts) != count:
        raise ValueError(f"Expected {count} numeric URDF value(s)")
    numbers = np.array([float(part) for part in parts])
    if not np.isfinite(numbers).all() or np.max(np.abs(numbers)) > 1e6:
        raise ValueError("URDF numeric values must be finite and within supported magnitude 1e6")
    return numbers


def _urdf_tree(data):
    if not data or len(data) > 2 * 1024 * 1024:
        raise ValueError("A URDF of up to 2 MiB is required")
    text = data.decode("utf-8-sig")
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("URDF document types, entities and null bytes are unsupported")
    root, depth, count = None, 0, 0
    try:
        for event, node in ET.iterparse(io.StringIO(text), events=("start", "end")):
            if event == "start":
                if root is None:
                    root = node
                count += 1
                depth += 1
                if depth > 64 or count > 20000:
                    raise ValueError("URDF exceeds supported XML complexity")
            else:
                depth -= 1
    except ET.ParseError as exc:
        raise ValueError("Invalid URDF XML") from exc
    if root is None or root.tag != "robot":
        raise ValueError("This adapter requires a URDF robot root")
    links = [n.get("name", "") for n in root.findall("link")]
    joints = root.findall("joint")
    if not 2 <= len(links) <= 65 or len(joints) != len(links) - 1:
        raise ValueError("A connected tree with 2–65 links and one fewer joint is required")
    if len(set(links)) != len(links) or any(not n.strip() or len(n) > 100 for n in links):
        raise ValueError("URDF link names must be unique, nonempty and at most 100 characters")
    by_child, names = {}, set()
    for node in joints:
        name, kind = node.get("name", ""), node.get("type")
        if not name.strip() or len(name) > 100 or name in names:
            raise ValueError("URDF joints require unique names of 1–100 characters")
        if kind not in ("fixed", "revolute", "prismatic") or node.find("safety_controller") is not None:
            raise ValueError(f"{name}: only fixed and bounded revolute/prismatic joints without soft-limit controllers are supported")
        names.add(name)
        parent = _child(node, "parent", True).get("link")
        child = _child(node, "child", True).get("link")
        if parent not in links or child not in links or parent == child or child in by_child:
            raise ValueError(f"{name}: invalid parent/child link or repeated child")
        pose = np.eye(4)
        origin = _child(node, "origin")
        if origin is not None:
            pose[:3, 3] = _numbers(origin.get("xyz", "0 0 0"), 3)
            pose[:3, :3] = Rotation.from_euler("xyz", _numbers(origin.get("rpy", "0 0 0"), 3)).as_matrix()
        axis, low, high, velocity = np.zeros(3), 0.0, 0.0, 0.0
        if kind != "fixed":
            axis_node = _child(node, "axis")
            axis = _numbers("1 0 0" if axis_node is None else axis_node.get("xyz"), 3)
            norm = float(np.linalg.norm(axis))
            if norm < 1e-12:
                raise ValueError(f"{name}: joint axis must be nonzero")
            axis = axis / norm
            limit = _child(node, "limit", True)
            low, high, velocity = [float(_numbers(limit.get(key), 1)[0]) for key in ("lower", "upper", "velocity")]
            if not low < high or velocity <= 0:
                raise ValueError(f"{name}: position limits must increase and velocity limit must be positive")
        mimic, rule = None, _child(node, "mimic")
        if rule is not None:
            if kind == "fixed":
                raise ValueError(f"{name}: a fixed link cannot mimic another joint")
            mimic = (rule.get("joint", ""), float(_numbers(rule.get("multiplier", "1"), 1)[0]),
                     float(_numbers(rule.get("offset", "0"), 1)[0]))
        by_child[child] = Joint(name, kind, parent, child, pose, axis, low, high, velocity, mimic)
    roots = set(links) - by_child.keys()
    if len(roots) != 1:
        raise ValueError("URDF requires one root and a connected acyclic tree")
    root_link = roots.pop()
    for link in links:
        visited = set()
        while link != root_link:
            if link in visited:
                raise ValueError("URDF has a disconnected cycle")
            visited.add(link)
            link = by_child[link].parent
    return root, root_link, by_child


def _mimic_order(joints):
    kinds = {j.name: j.kind for j in joints}
    ready = {j.name for j in joints if j.mimic is None}
    ordered = []
    pending = [j for j in joints if j.mimic is not None]
    while pending:
        resolved = [j for j in pending if j.mimic[0] in ready]
        if not resolved:
            raise ValueError("Mimic joints require named active sources without dependency cycles")
        for joint in resolved:
            if kinds[joint.mimic[0]] != joint.kind:
                raise ValueError("A mimic source and follower must have the same joint type and units")
            ready.add(joint.name)
        pending = [j for j in pending if j.name not in ready]
        ordered.extend(resolved)
    return ordered


def _tip_positions(path, positions, samples):
    world = np.repeat(np.eye(4)[None, :, :], samples, axis=0)
    for joint in path:
        world = world @ joint.origin
        if joint.kind == "fixed":
            continue
        motion = np.repeat(np.eye(4)[None, :, :], samples, axis=0)
        displacement = positions[joint.name][:, None] * joint.axis
        if joint.kind == "prismatic":
            motion[:, :3, 3] = displacement
        else:
            motion[:, :3, :3] = Rotation.from_rotvec(displacement).as_matrix()
        world = world @ motion
    return world[:, :3, 3]


def _kinematic_motion(request, joints, start, target, times):
    positions, peak_speeds = {}, {}
    for joint in joints:
        name = joint.name
        delta = target[name] - start[name]
        if request.mode == "prescribed":
            position = start[name] + (times / request.duration_s) * delta
            peak = abs(delta) / request.duration_s
        else:
            # Exact step response of dq/dt = clip(gain*(target-q), -velocity, velocity).
            gain = 1 / request.time_constant_s if request.time_constant_s is not None else request.gain_per_s
            transition = max(0.0, abs(delta) / joint.velocity - 1.0 / gain)
            linear = joint.velocity * np.minimum(times, transition)
            residual = min(abs(delta), joint.velocity / gain)
            exponential = residual * -np.expm1(-gain * np.maximum(0, times - transition))
            position = start[name] + np.sign(delta) * (linear + exponential)
            peak = min(joint.velocity, gain * abs(delta))
        positions[name] = position
        peak_speeds[name] = peak
    return positions, peak_speeds


def run_robot(request: RobotRunRequest, model_bytes: bytes | None = None, controller_bytes: bytes | None = None) -> dict:
    if (request.model_asset_id is None) != (model_bytes is None):
        raise ValueError("Supply model bytes for an uploaded model ID; omit both for the built-in reference")
    if (request.controller_asset_id is None) != (controller_bytes is None):
        raise ValueError("A selected controller asset requires its matching JSON bytes")
    if controller_bytes is not None and request.mode != "mujoco_pd":
        raise ValueError("A torque controller requires mujoco_pd mode")
    data = HAND_URDF if model_bytes is None else model_bytes
    model_xml, root, by_child = _urdf_tree(data)
    joints = [j for j in by_child.values() if j.kind != "fixed"]
    independent = [j for j in joints if j.mimic is None]
    followers = _mimic_order(joints)
    active = {j.name for j in independent}
    unknown = (request.targets.keys() | request.initial.keys()) - active
    if unknown:
        raise ValueError(f"Unknown or fixed/mimic commanded joints: {', '.join(sorted(unknown))}")
    if request.time_constant_s is not None and any(j.name in request.targets and j.kind != "revolute" for j in independent):
        raise ValueError("The joint-response time constant applies to a rotational joint measured in radians")
    start = {j.name: request.initial.get(j.name, 0.0) for j in independent}
    target = {**start, **request.targets}
    for joint in followers:
        source, scale, offset = joint.mimic
        start[joint.name] = scale * start[source] + offset
        target[joint.name] = scale * target[source] + offset
    for joint in joints:
        if any(not joint.lower <= q <= joint.upper for q in (start[joint.name], target[joint.name])):
            raise ValueError(f"{joint.name}: initial and target positions must lie in [{joint.lower}, {joint.upper}]")
    leaves = sorted(set(by_child) - {j.parent for j in by_child.values()})
    if request.tip_link is None and model_bytes is not None and len(leaves) > 1:
        raise ValueError("Select a tip_link from the model leaves: " + ", ".join(leaves))
    tip = request.tip_link or leaves[0]
    if tip not in by_child:
        raise ValueError("Tip must be a link downstream of the root")
    path, cursor = [], tip
    while cursor != root:
        path.append(by_child[cursor])
        cursor = by_child[cursor].parent
    times = np.linspace(0, request.duration_s, request.samples)
    dynamics = None
    if request.mode == "mujoco_pd":
        if followers:
            raise ValueError("Dynamic import requires independent movable joints; use kinematic motion for mimic joints")
        from .robot_dynamics import dynamic_motion
        times, positions, peak_speeds, dynamics = dynamic_motion(
            request, model_xml, root, by_child, tip, start, target, controller_bytes)
    else:
        positions, peak_speeds = _kinematic_motion(request, independent, start, target, times)
        for joint in followers:
            source, scale, offset = joint.mimic
            positions[joint.name] = scale * positions[source] + offset
            peak_speeds[joint.name] = abs(scale) * peak_speeds[source]
    tip_xyz = _tip_positions(reversed(path), positions, len(times))
    if dynamics is not None and model_bytes is not None:
        if not np.allclose(dynamics["final_tip_xyz_m"], tip_xyz[-1], rtol=1e-10, atol=1e-8):
            raise ValueError("Compiled terminal link frame disagrees with the URDF forward kinematics")
    errors = {n: abs(target[n] - float(positions[n][-1])) for n in start}
    if dynamics is None:
        within_positions = all(np.min(positions[j.name]) >= j.lower - 1e-9 and
                               np.max(positions[j.name]) <= j.upper + 1e-9 for j in joints)
    else:
        within_positions = dynamics["within_joint_limits"]
    within_speeds = all(peak_speeds[j.name] <= j.velocity + 1e-9 for j in joints)
    reached = all(error <= request.tolerance for error in errors.values())
    if dynamics is None:
        adapter = "urdf-kinematics-v1"
    else:
        adapter = "mujoco-hand-pd-v1" if model_bytes is None else "urdf-primitive-pd-v1"
    qualification_passed = dynamics is None or all(check["passed"] for check in dynamics["reference_qualification"])
    criteria = {"joint_target_tolerance": request.tolerance, "check_all_joint_position_and_velocity_limits": True,
                "qualification_required": dynamics is not None}
    if request.time_constant_s is not None:
        criteria["servo_response"] = {"joint": next(iter(request.targets)), "time_constant_s": request.time_constant_s,
                                      "effective_gain_per_s": 1 / request.time_constant_s}
    return {"adapter": adapter, "mode": request.mode, "passed": bool(reached and within_speeds and within_positions) if qualification_passed else None,
            "criteria": criteria,
            "model": {"name": model_xml.get("name", ""), "asset_id": request.model_asset_id, "reference_id": "two_finger_hand_v1" if model_bytes is None else None,
                      "urdf_sha256": hashlib.sha256(data).hexdigest(), "root_link": root, "tip_link": tip,
                      "joints": [{"name": j.name, "parent": j.parent, "child": j.child, "type": j.kind, "axis_in_joint_frame": j.axis.tolist(),
                                  "unit": "rad" if j.kind == "revolute" else "m", "limits": [j.lower, j.upper],
                                  "mimic": {"source": j.mimic[0], "multiplier": j.mimic[1], "offset": j.mimic[2]} if j.mimic else None,
                                  "velocity_limit": j.velocity} for j in joints]},
            "metrics": {"final_absolute_joint_error": errors, "peak_joint_speed": peak_speeds, "within_joint_limits": bool(within_positions),
                        "within_velocity_limits": bool(within_speeds), "target_reached": reached,
                        "tip_displacement_m": float(np.linalg.norm(tip_xyz[-1] - tip_xyz[0])),
                        "tip_sampled_path_length_m": float(np.linalg.norm(np.diff(tip_xyz, axis=0), axis=1).sum())},
            "trajectory": {"time_s": times.tolist(), "joint_positions": {n: q.tolist() for n, q in positions.items()},
                           "tip_xyz_m": tip_xyz.tolist()}, "dynamics": dynamics,
            "scope": "Fixed-base rigid-body joint tracking with bounded generalized forces." if dynamics is not None else
                     "Forward kinematics of link frames; geometry, contact, inertia and actuator dynamics are excluded."}
