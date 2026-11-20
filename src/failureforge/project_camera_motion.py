"""Tabletop camera reconstructions using saved poses and verified model geometry."""
from __future__ import annotations

import hashlib
from xml.etree import ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation

from .camera_mesh import mesh_surface, stl_triangles
from .camera_scene import Camera, Frame, Object3D, Scene
from .project_replay import link_trajectories
from .project_robot import HAND_URDF, _numbers, _urdf_tree
from .robot_dynamics import HAND_MJCF
from .urdf_mjcf import _pose


STEEL = (.66, .72, .74)
GRAPHITE = (.19, .24, .27)
BLACK = (.10, .14, .16)
TEAL = (.14, .53, .49)
AMBER = (.95, .48, .12)


class _Assembly:
    """One ordered set of render objects with their world poses at each saved sample."""
    def __init__(self, times):
        self.times = np.asarray(times, dtype=float)
        self.objects, self.positions, self.rotations = [], [], []

    def add(self, obj, position, rotation=None):
        self.objects.append(obj)
        self.positions.append(np.broadcast_to(position, (len(self.times), 3)))
        orientation = np.eye(3) if rotation is None else rotation
        self.rotations.append(np.broadcast_to(orientation, (len(self.times), 3, 3)))

    def add_shape(self, kind, size, color, position, rotation=None):
        self.add(Object3D(kind, tuple(size), color), position, rotation)

    def bounds(self):
        low, high = np.full(3, np.inf), np.full(3, -np.inf)
        for obj, pos, rot in zip(self.objects, self.positions, self.rotations):
            center = np.zeros(3)
            if obj.kind == "mesh":
                lo, hi = np.min(obj.vertices, axis=0), np.max(obj.vertices, axis=0)
                center, half = (lo + hi) / 2, (hi - lo) / 2
            elif obj.kind == "box":
                half = np.asarray(obj.size)
            elif obj.kind == "sphere":
                half = np.repeat(obj.size[0], 3)
            else:
                radius, height = obj.size
                half = np.array([radius, radius, height + (radius if obj.kind == "capsule" else 0)])
            world = pos + rot @ center
            radius = np.abs(rot) @ half
            low = np.minimum(low, (world-radius).min(axis=0))
            high = np.maximum(high, (world+radius).max(axis=0))
        return low, high

    def scene(self, camera_at, labels, description, floor_z, colors_at=None):
        positions = np.stack(self.positions, axis=1)
        rotations = np.stack(self.rotations, axis=1)
        elapsed = self.times - self.times[0]

        def frame(t):
            index = int(np.clip(np.searchsorted(elapsed, t, side="right")-1, 0, len(elapsed)-1))
            return Frame(positions[index], rotations[index], camera_at(index), colors_at(index) if colors_at else None)
        return Scene(self.objects, float(elapsed[-1]), labels, description, frame, float(floor_z))


def _bench(assembly, center, span, top):
    x, y = center
    width, depth = .91*span, .66*span
    assembly.add_shape("box", (width, depth, .023*span), (.61,.66,.65), (x,y,top-.023*span))
    assembly.add_shape("box", (.98*width, .97*depth, .046*span), GRAPHITE, (x,y,top-.092*span))
    for dx in (-.88*width, .88*width):
        for dy in (-.82*depth, .82*depth):
            assembly.add_shape("cylinder", (.022*span,.002*span), BLACK, (x+dx,y+dy,top+.001*span))
            assembly.add_shape("box", (.056*span,.047*span,.078*span), STEEL, (x+dx,y+dy,top-.19*span))
    return top-.269*span


def _along(vector):
    """Right-handed orientation whose local Z follows the supplied 3D vector."""
    direction = np.asarray(vector, dtype=float)
    z = direction / np.linalg.norm(direction)
    reference = [1., 0., 0.] if abs(z[0]) < .85 else [0., 1., 0.]
    y = np.cross(z, reference)
    y /= np.linalg.norm(y)
    return np.column_stack((np.cross(y, z), y, z))


def _camera(focus, offset, fovy=40):
    target = np.asarray(focus, dtype=float)
    return Camera(tuple(target + offset), tuple(target), fovy=fovy)


def _sdf_pose(element, parent):
    pose = element.find("pose")
    if pose is None:
        return np.zeros(3), np.eye(3)
    if pose.get("relative_to", "") not in ("", parent):
        raise ValueError("Camera pose uses another reference frame")
    form = pose.get("rotation_format", "euler_rpy")
    if form == "euler_rpy":
        values = _numbers(pose.text, 6)
        rotation = Rotation.from_euler("xyz", values[3:], degrees=pose.get("degrees","false").lower() in ("true","1"))
    elif form == "quat_xyzw":
        values = _numbers(pose.text, 7)
        rotation = Rotation.from_quat(values[3:])
    else:
        raise ValueError("Unsupported camera pose rotation")
    return values[:3], rotation.as_matrix()


def _gazebo_cameras(xml, tree, positions, rotations, span):
    """Supported attached pinhole cameras use the Gazebo +X view and +Z up axes."""
    cameras = []
    for extension in xml.findall("gazebo"):
        link = extension.get("reference")
        if link not in positions:
            continue
        mount = link
        while mount in tree and tree[mount].kind == "fixed":
            mount = tree[mount].parent
        moving = mount in tree
        for sensor in extension.findall("sensor"):
            if sum(entry[0] == moving for entry in cameras) == 2:
                break
            camera = sensor.find("camera")
            if sensor.get("type") != "camera" or camera is None:
                continue
            try:
                if camera.findtext("lens/type","gnomonical") != "gnomonical":
                    continue
                if any(float(camera.findtext("distortion/"+k,"0")) != 0 for k in ("k1","k2","k3","p1","p2")):
                    continue
                hfov = float(camera.findtext("horizontal_fov", "1.0471975512"))
                width = int(camera.findtext("image/width","320"))
                height = int(camera.findtext("image/height","240"))
                if width <= 0 or height <= 0 or not 0 < hfov < np.pi:
                    continue
                ratio = width/height
                fovy = float(np.degrees(2*np.arctan(np.tan(hfov/2)/ratio)))
                local, basis = _sdf_pose(sensor, link)
                offset, orientation = _sdf_pose(camera, sensor.get("name"))
            except (TypeError, ValueError, OverflowError):
                continue
            eye = positions[link] + rotations[link] @ (local + basis @ offset)
            world = rotations[link] @ (basis @ orientation)
            target = eye + span*world[:,:,0]
            up = world[:,:,2]
            views = [Camera(tuple(p),tuple(q),tuple(u),fovy=fovy,aspect=ratio) for p,q,u in zip(eye,target,up)]
            label = sensor.get("name") or camera.get("name") or "Model camera"
            cameras.append((moving, label + " (rendered)", views))
    main, detail = None, None
    if len(cameras) == 1:
        detail = cameras[0]
    elif cameras:
        main = next((item for item in cameras if not item[0]), cameras[0])
        rest = [item for item in cameras if item is not main]
        detail = next((item for item in rest if item[0]), rest[0])
    return main, detail


def _robot_frames(result, model_bytes):
    # The replay checker verifies the model hash, joint arrays and reconstructed tip.
    motion = link_trajectories(result, model_bytes)
    xml, root, tree = _urdf_tree(model_bytes)
    times = np.asarray(motion["time_s"])
    positions = {link["name"]: np.asarray(link["xyz_m"]) for link in motion["links"]}
    rotations = {root: np.broadcast_to(np.eye(3), (len(times),3,3))}
    joint_positions = result["trajectory"]["joint_positions"]

    def orientation(name):
        if name not in rotations:
            joint = tree[name]
            world = orientation(joint.parent) @ joint.origin[:3,:3]
            if joint.kind == "revolute":
                angle = np.asarray(joint_positions[joint.name])[:,None]
                world = world @ Rotation.from_rotvec(angle * joint.axis).as_matrix()
            rotations[name] = world
        return rotations[name]
    for child in tree:
        orientation(child)
    return xml, root, tree, times, positions, rotations


def _material(node, palette):
    local = node.find("material")
    if local is None:
        return STEEL
    rgba = local.find("color")
    if rgba is None:
        return palette.get(local.get("name"), STEEL)
    return tuple(np.clip(_numbers(rgba.get("rgba"), 4)[:3], 0, 1))


def _visual(node, color, meshes, cache, face_budget):
    geometry = node.find("geometry")
    if geometry is None or len(geometry) != 1:
        return None, False
    shape = geometry[0]
    if shape.tag == "mesh":
        uri = shape.get("filename")
        if not uri or uri not in meshes:
            return None, False
        if uri not in cache:
            cache[uri] = mesh_surface(stl_triangles(meshes[uri]), face_budget)
        vertices, faces, simplified = cache[uri]
        scale = _numbers(shape.get("scale", "1 1 1"), 3)
        if np.any(scale == 0):
            return None, False
        return Object3D("mesh", (), color, vertices * scale, faces), simplified
    if shape.tag == "box":
        size = _numbers(shape.get("size"), 3) / 2
    elif shape.tag == "cylinder":
        size = [_numbers(shape.get("radius"), 1)[0], _numbers(shape.get("length"), 1)[0]/2]
    elif shape.tag == "sphere":
        size = _numbers(shape.get("radius"), 1)
    else:
        return None, False
    return (Object3D(shape.tag, tuple(size), color), False) if min(size) > 0 else (None, False)


def _reference_fingers(assembly, positions, rotations):
    mjcf = ET.fromstring(HAND_MJCF)
    default = mjcf.find("default/geom")
    for finger in mjcf.findall("worldbody/body/body"):
        name = finger.get("name")
        geom = finger.find("geom")
        ends = _numbers(geom.get("fromto", default.get("fromto")), 6).reshape(2,3)
        axis = ends[1] - ends[0]
        radius = _numbers(geom.get("size", default.get("size")), 1)[0]
        assembly.add_shape("capsule", (radius, np.linalg.norm(axis)/2), (.32,.40,.44),
                           positions[name] + rotations[name] @ ends.mean(axis=0), rotations[name] @ _along(axis))
    # The palm has no solved surface. This removable mounting plate indicates its fixed location.
    assembly.add_shape("box", (.067,.016,.0055), GRAPHITE, (0,-.009,-.012))
    for name in ("left_finger", "right_finger"):
        assembly.add_shape("cylinder", (.009,.003), STEEL, positions[name] + [0,0,-.008])


def _tool_path(result):
    trace = result.get("trajectory") or {}
    times = np.asarray(trace.get("time_s", []), dtype=float)
    tip = np.asarray(trace.get("tip_xyz_m", []), dtype=float)
    if times.ndim != 1 or not 2 <= len(times) <= 241 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
        return None
    if tip.shape != (len(times),3) or not np.isfinite(tip).all():
        return None
    span = max(float(np.ptp(tip, axis=0).max()), .03)
    center = (tip.min(axis=0) + tip.max(axis=0))/2
    assembly = _Assembly(times)
    for point in tip[np.unique(np.linspace(0,len(times)-1,min(32,len(times)),dtype=int))]:
        assembly.add_shape("sphere", (.009*span,), STEEL, point)
    assembly.add_shape("sphere", (.035*span,), TEAL, tip)
    floor = _bench(assembly, center[:2], span, float(tip[:,2].min() - .08*span))
    main = _camera(center, span*np.array([.94,-1.43,.83]))
    return assembly.scene(lambda i: (main, _camera(tip[i],span*np.array([-.54,-.48,.28]))),
                          ("Workcell overview","Tip close-up"),
                          "The green marker follows the saved tip positions. The dotted path and work surface are illustrative. "
                          "This recording has no verified robot surface.", floor)


def _robot(result, model_bytes, meshes):
    model = result.get("model") or {}
    if model_bytes is None and model.get("reference_id") == "two_finger_hand_v1":
        model_bytes = HAND_URDF
    if not model_bytes:
        return _tool_path(result)
    xml, root, tree, times, positions, rotations = _robot_frames(result, model_bytes)
    assembly = _Assembly(times)
    notes = []
    digest = (result.get("dynamics") or {}).get("mjcf_sha256")
    reference_hand = (model_bytes == HAND_URDF and model.get("reference_id") == "two_finger_hand_v1" and
                      (digest is None or digest == hashlib.sha256(HAND_MJCF.encode()).hexdigest()))
    if reference_hand:
        _reference_fingers(assembly, positions, rotations)
        notes.append("Finger capsules use the reference MJCF dimensions. The palm mounting plate is illustrative.")
    else:
        palette = {m.get("name"): tuple(np.clip(_numbers(m.find("color").get("rgba"),4)[:3],0,1))
                   for m in xml.findall("material") if m.find("color") is not None}
        all_origins = np.concatenate(list(positions.values()))
        marker = max(float(np.ptp(all_origins,axis=0).max()) * .015, .0006)
        mesh_count = len(xml.findall("link/visual/geometry/mesh")) or len(xml.findall("link/collision/geometry/mesh"))
        budget = min(24000, max(250, 160000 // max(1, mesh_count)))
        cache, surfaced = {}, set()
        missing, collision, reduced = False, False, False
        for link in xml.findall("link"):
            name = link.get("name")
            for tag in ("visual", "collision"):
                for node in link.findall(tag):
                    if len(assembly.objects) >= 512:
                        raise ValueError("Model exceeds the camera surface limit")
                    try:
                        obj, simpler = _visual(node, _material(node, palette), meshes, cache, budget)
                        offset, orientation = _pose(node)
                    except (UnicodeError, ValueError, TypeError):
                        missing = True
                        continue
                    if obj is None:
                        missing = True
                        continue
                    assembly.add(obj, positions[name] + rotations[name] @ offset, rotations[name] @ orientation.as_matrix())
                    surfaced.add(name)
                    collision |= tag == "collision"
                    reduced |= simpler
                if name in surfaced:
                    break
        for child, joint in tree.items():
            parent = joint.parent
            delta = joint.origin[:3,3]
            length = np.linalg.norm(delta)
            if parent not in surfaced and length > 1e-9:
                assembly.add_shape("cylinder", (marker*.7,length/2), GRAPHITE,
                                   positions[parent] + rotations[parent] @ (delta/2), rotations[parent] @ _along(delta))
                missing = True
            if child not in surfaced and joint.kind != "fixed":
                assembly.add_shape("sphere", (marker*1.4,), TEAL, positions[child])
                # An asymmetric fiducial makes rotation visible even for a zero-length joint.
                direction = _along(joint.axis)[:,0] * marker*3.5
                assembly.add_shape("capsule", (marker*.45,np.linalg.norm(direction)/2), AMBER,
                                   positions[child] + rotations[child] @ (direction/2), rotations[child] @ _along(direction))
                missing = True
        if not assembly.objects:
            return _tool_path(result)
        if missing:
            notes.append("Frame guides indicate link origins where source surfaces are unavailable.")
        if collision:
            notes.append("Some links use their recorded model’s collision shapes.")
        if reduced:
            notes.append(f"Dense meshes are simplified to at most {budget} faces per surface for playback.")
    lo, hi = assembly.bounds()
    span = max(float(np.max(hi-lo)), .015)
    center = (lo+hi)/2
    # Workholding plate under the model. Its height leaves the entire recorded envelope clear.
    mount_xy = positions[root][0,:2]
    plate_z = lo[2]-.011*span
    plate_size = (.52,.25) if reference_hand else (.20,.16)
    assembly.add_shape("box",(plate_size[0]*span,plate_size[1]*span,.01*span),
                       (.43,.48,.48),(*mount_xy,plate_z))
    for dx in (-.82,.82):
        for dy in (-.77,.77):
            assembly.add_shape("cylinder",(.015*span,.003*span),BLACK,
                               (*(mount_xy + np.array(plate_size)*[dx,dy]*span),plate_z+.011*span))
    floor = _bench(assembly, center[:2], span, plate_z-.01*span)
    tip = positions[model["tip_link"]]
    direction = (tip.mean(axis=0)-positions[root][0])[:2]
    direction = direction / np.linalg.norm(direction) if np.linalg.norm(direction) > 1e-9 else np.array([0.,1.])
    side = np.array([direction[1],-direction[0]])
    main = _camera(center, span*np.r_[1.45*side + .33*direction, .78])
    detail_scale = .69*span if reference_hand else .58*span
    model_main, model_detail = _gazebo_cameras(xml, tree, positions, rotations, span)
    def cameras(i):
        close = _camera(tip[i], detail_scale*np.array([-.65,.87,.72]))
        return model_main[2][i] if model_main else main, model_detail[2][i] if model_detail else close
    labels = (model_main[1] if model_main else "Workcell overview", model_detail[1] if model_detail else "Tool close-up")
    if model_detail:
        notes.append("Views labeled rendered use the camera poses and fields of view declared in the model.")
    description = "Virtual cameras show joint samples from this run in the verified URDF frames. " + " ".join(notes)
    return assembly.scene(cameras, labels, description.rstrip() + " The workbench and mounting plate are illustrative.", floor)


def _arrow(color, length):
    # The force indicator points toward -Z. Its tip is the local origin.
    sides = 12
    phi = 2*np.pi*np.arange(sides)/sides
    rings = [np.column_stack((radius*np.cos(phi),radius*np.sin(phi),np.full(sides,z)))
             for z, radius in ((length, .003),(.014,.003),(.014,.009))]
    vertices = np.vstack((*rings, [0.,0.,0.]))
    faces = []
    for i in range(sides):
        j = (i+1) % sides
        for start in (0,sides):
            faces.extend([(start+i,start+j,start+sides+i), (start+j,start+sides+j,start+sides+i)])
        faces.append((2*sides+i,2*sides+j,3*sides))
    return Object3D("mesh", (), color, vertices, np.asarray(faces,dtype=int))


def _lift(result, mark_events=True):
    series, fixture = result.get("series") or {}, result.get("fixture") or {}
    times = np.asarray(series.get("time_s",[]), dtype=float)
    z = np.asarray(series.get("position_m",[]), dtype=float)
    force = np.asarray(series.get("applied_head_force_n",[]), dtype=float)
    if times.ndim != 1 or not 2 <= len(times) <= 5000 or not np.isfinite(times).all() or not np.all(np.diff(times)>0):
        return None
    if z.shape != times.shape or not np.isfinite(z).all() or force.shape != times.shape or not np.isfinite(force).all():
        return None
    target, tolerance = fixture.get("target_m"), fixture.get("error_limit_m")
    if not isinstance(target,(int,float)) or not isinstance(tolerance,(int,float)) or not np.isfinite([target,tolerance]).all() or tolerance < 0:
        return None
    payload = (result.get("summary") or {}).get("payload_kg")
    assembly = _Assembly(times)
    rail_top = max(z.max(), target+tolerance) + .061
    base = min(z.min(), target-tolerance, 0.) - .043
    assembly.add_shape("box", (.11,.082,.009), GRAPHITE, (0,0,base+.009))
    for x in (-.067,.067):
        assembly.add_shape("cylinder", (.0063, (rail_top-base-.014)/2), STEEL, (x,.049,(rail_top+base+.014)/2))
    assembly.add_shape("box", (.085,.018,.009), GRAPHITE, (0,.049,rail_top))
    assembly.add_shape("box", (.013,.012,(rail_top-base)/2), (.34,.39,.40), (0,.061,(rail_top+base)/2))
    moving = np.column_stack((np.zeros(len(z)),np.zeros(len(z)),z))
    platform = len(assembly.objects)
    assembly.add_shape("box", (.093,.066,.0045), TEAL, moving+[0,-.008,-.0045])
    for x in (-.067,.067):
        assembly.add_shape("cylinder", (.011,.009), GRAPHITE, moving+[x,.049,-.008])
    height = 0.
    if isinstance(payload,(int,float)) and payload > 0:
        height = .043
        assembly.add_shape("box", (.039,.032,height/2), (.72,.48,.26), moving+[0,-.018,height/2])
        assembly.add_shape("box", (.005,.0322,.00035), (.88,.73,.48), moving+[0,-.018,height+.00035])
    # A station scale fixed in the world marks the actual target and its allowed interval.
    assembly.add_shape("box", (.007,.003,(rail_top-base)/2), (.82,.83,.78), (.091,.047,(rail_top+base)/2))
    for level in np.arange(base+.015, rail_top, .025)[:64]:
        assembly.add_shape("box", (.004,.0007,.0006), GRAPHITE, (.091,.0436,level))
    for level in (target-tolerance, target, target+tolerance):
        assembly.add_shape("box", (.009,.001,.0015), TEAL, (.091,.0428,level))
    floor = _bench(assembly,(0,0),.285,base)
    if np.any(force>0):
        tip = moving+[0,-.018,height+.01]
        # Hide the indicator beneath the opaque floor during unloaded samples.
        tip[force<=0,2] = floor-.14
        assembly.add(_arrow(AMBER, .022+.004*min(5.,force.max())),tip)
    center = np.array([0.,0.,(rail_top+base)/2])
    main = _camera(center, np.array([.34,-.44,.245]), 37.)
    focus = np.array([0.,-.006, (z.min()+max(z.max()+height, target+tolerance))/2])
    detail = _camera(focus,np.array([-.265,-.37,.12]), 40.)
    description = (f"Platform height follows the saved samples. The scale marks {1000*target:g} mm with a "
                   f"{1000*tolerance:g} mm tolerance.")
    if isinstance(payload,(int,float)) and np.isfinite(payload):
        description += f" The secured payload is {payload:g} kg."
    if force.max() > 0:
        description += f" The orange arrow marks the recorded downward head load of {force.max():g} N."
    else:
        description += " The recorded head load is 0 N throughout."
    peak = (result.get("summary") or {}).get("max_hold_error_m")
    if isinstance(peak,(int,float)) and np.isfinite(peak):
        description += f" Maximum height error during the hold was {1000*peak:.2f} mm."
    start, end = fixture.get("arrival_deadline_s"), fixture.get("end_time_s")
    colors_at = None
    if mark_events and all(isinstance(t, (int, float)) and np.isfinite(t) for t in (start, end)) and start < end:
        above = (times >= start) & (times <= end) & (np.abs(z-target) > tolerance)
        indices = np.flatnonzero(above)
        if len(indices):
            i = indices[0]
            colors = np.array([obj.color for obj in assembly.objects])
            colors[platform] = (.86,.18,.52)
            colors_at = lambda index: colors if above[index] else None
            description += (f" The platform turns pink at above-limit hold samples. The first is "
                            f"{times[i]:.6g} s with {1000*abs(z[i]-target):.5g} mm height error.")
    description += " The station hardware, parcel appearance and workbench are illustrative."
    return assembly.scene(lambda i: (main,detail), ("Workcell overview","Station close-up"),description,floor,colors_at)


def motion_scene(run, model_bytes=None, meshes=None):
    """Build a virtual camera scene from an immutable stored project run."""
    result = run.get("result")
    if not isinstance(result, dict):
        return None
    if run.get("adapter") in ("packaging_lift", "packaging_lift_timed_v2"):
        valid = not (run.get('assessment_error') or run.get('error') or
                     (result.get('numerical_diagnostics') or {}).get('passed') is False)
        return _lift(result, mark_events=valid)
    if run.get("adapter") == "robot_motion":
        return _robot(result,model_bytes,meshes or {})
    return None
