"""Translate validated rigid links and primitive collisions to a closed MJCF document."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation

from .project_robot import _child, _numbers


def _scalar(node, key):
    return float(_numbers(node.get(key), 1)[0])


def _vector(values):
    return " ".join(format(float(v), ".17g") for v in values)


def _pose(node):
    origin = _child(node, "origin")
    if origin is None:
        return np.zeros(3), Rotation.identity()
    return _numbers(origin.get("xyz", "0 0 0"), 3), Rotation.from_euler("xyz", _numbers(origin.get("rpy", "0 0 0"), 3))


def _insert_inertia(body, node):
    mass = _scalar(_child(node, "mass", True), "value")
    moment = _child(node, "inertia", True)
    xx, yy, zz, xy, xz, yz = [_scalar(moment, f"i{k}") for k in ("xx", "yy", "zz", "xy", "xz", "yz")]
    tensor = np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]])
    principal = np.linalg.eigvalsh(tensor)
    if mass <= 0 or principal[0] <= 1e-12 or principal[2] > principal[0] + principal[1] + 1e-10 * principal[2]:
        raise ValueError("URDF requires positive mass and a physically admissible positive-definite inertia tensor at the COM")
    xyz, rotation = _pose(node)
    matrix = rotation.as_matrix()
    rotated = matrix @ tensor @ matrix.T
    full = [rotated[i, j] for i, j in ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))]
    ET.SubElement(body, "inertial", pos=_vector(xyz), mass=str(mass), fullinertia=_vector(full))


def _insert_collision(body, collision):
    geometry = _child(collision, "geometry", True)
    if len(geometry) != 1:
        raise ValueError("Each URDF collision needs one primitive geometry")
    shape = geometry[0]
    if shape.tag == "box":
        size = _numbers(shape.get("size"), 3) / 2
    elif shape.tag == "sphere":
        size = [_scalar(shape, "radius")]
    elif shape.tag == "cylinder":
        size = [_scalar(shape, "radius"), _scalar(shape, "length") / 2]
    else:
        raise ValueError("Dynamic collision geometry must be a box, sphere or cylinder")
    if any(value <= 0 for value in size):
        raise ValueError("Collision geometry dimensions must be positive")
    xyz, rotation = _pose(collision)
    ET.SubElement(body, "geom", type=shape.tag, pos=_vector(xyz),
                  quat=_vector(rotation.as_quat(scalar_first=True)), size=_vector(size))


def primitive_mjcf(robot, root, by_child, tip):
    """External resources never enter the generated document."""
    if any(element.tag not in {"link", "joint", "material"} for element in robot):
        raise ValueError("Dynamic import accepts standard URDF links, joints and materials without model extensions")
    links = {link.get("name"): link for link in robot.findall("link")}
    source_joints = {joint.get("name"): joint for joint in robot.findall("joint")}
    if sum(len(link.findall("collision")) for link in links.values()) > 128:
        raise ValueError("Primitive dynamic models support at most 128 collision geometries")
    model = ET.Element("mujoco", model="FailureForge imported articulated model")
    ET.SubElement(model, "compiler", angle="radian", inertiafromgeom="false", fusestatic="false")
    ET.SubElement(model, "option", timestep="0.001", gravity="0 0 -9.81", integrator="implicitfast")
    world = ET.SubElement(model, "worldbody")
    motors = ET.SubElement(model, "actuator")
    effort = {}
    bodies = {root: ET.SubElement(world, "body", name=root)}
    queue = [root]
    while queue:
        name = queue.pop()
        body = bodies[name]
        link = links[name]
        moving = name in by_child and by_child[name].kind != "fixed"
        collisions = link.findall("collision")
        inertia = _child(link, "inertial")
        if moving and not collisions:
            raise ValueError(f"{name}: a moving link requires primitive collision geometry")
        if inertia is None and (moving or (name != root and collisions)):
            raise ValueError(f"{name}: explicit inertia is required for a moving link or attached collision body")
        if inertia is not None:
            _insert_inertia(body, inertia)
        for collision in collisions:
            _insert_collision(body, collision)
        if name == tip:
            ET.SubElement(body, "site", name="tracked_tip", size="0.0001")
        for joint in by_child.values():
            if joint.parent != name:
                continue
            quat = Rotation.from_matrix(joint.origin[:3, :3]).as_quat(scalar_first=True)
            child = ET.SubElement(body, "body", name=joint.child, pos=_vector(joint.origin[:3, 3]), quat=_vector(quat))
            bodies[joint.child] = child
            queue.append(joint.child)
            if joint.kind == "fixed":
                continue
            source = source_joints[joint.name]
            limit = _child(source, "limit", True)
            force = _scalar(limit, "effort")
            if force <= 0:
                raise ValueError(f"{joint.name}: a positive effort limit is required")
            effort[joint.name] = force
            joint_props = {}
            dynamics = _child(source, "dynamics")
            if dynamics is not None:
                for key, attribute in (("damping", "damping"), ("friction", "frictionloss")):
                    if key in dynamics.attrib:
                        value = _scalar(dynamics, key)
                        if value < 0:
                            raise ValueError("Joint damping and friction must be nonnegative")
                        joint_props[attribute] = str(value)
            ET.SubElement(child, "joint", name=joint.name, type="hinge" if joint.kind == "revolute" else "slide",
                          axis=_vector(joint.axis), range=_vector([joint.lower, joint.upper]), limited="true", **joint_props)
            ET.SubElement(motors, "motor", name=joint.name, joint=joint.name, ctrllimited="true", ctrlrange=_vector([-force, force]))
    return ET.tostring(model, encoding="unicode"), effort
