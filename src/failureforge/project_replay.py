"""Reconstruct joint-frame positions from a verified model and its recorded samples."""
import hashlib

import numpy as np
from fastapi import APIRouter, HTTPException

from .project_bundle import evidence
from .project_robot import HAND_URDF, _tip_positions, _urdf_tree


def link_trajectories(result, model_bytes):
    model, trajectory = result["model"], result["trajectory"]
    if hashlib.sha256(model_bytes).hexdigest() != model["urdf_sha256"]:
        raise ValueError("The stored model differs from the recorded URDF")
    _, root, tree = _urdf_tree(model_bytes)
    times = np.asarray(trajectory["time_s"], dtype=float)
    if times.ndim != 1 or not 2 <= len(times) <= 241 or not np.all(np.isfinite(times)) or not np.all(np.diff(times) > 0):
        raise ValueError("Missing or invalid recorded sample times")
    positions = {}
    for joint in tree.values():
        if joint.kind != "fixed":
            values = np.asarray(trajectory["joint_positions"][joint.name], dtype=float)
            if values.shape != times.shape or not np.all(np.isfinite(values)):
                raise ValueError("Missing or invalid recorded joint positions")
            positions[joint.name] = values
    links = [{"name": root, "parent": None, "xyz_m": [[0., 0., 0.]] * len(times)}]
    for name, joint in tree.items():
        path, cursor = [], name
        while cursor != root:
            path.append(tree[cursor])
            cursor = tree[cursor].parent
        xyz = _tip_positions(reversed(path), positions, len(times))
        if name == model["tip_link"] and not np.allclose(trajectory["tip_xyz_m"], xyz, rtol=1e-9, atol=1e-8):
            raise ValueError("Reconstructed tip disagrees with the recorded trajectory")
        links.append({"name": name, "parent": joint.parent, "xyz_m": xyz.tolist()})
    return {"root_link": root, "time_s": times.tolist(), "links": links}


def replay_router(runs):
    router = APIRouter(tags=["project replay"])

    @router.get("/api/projects/{project}/analysis/{run}/replay-geometry")
    def geometry(project: str, run: str):
        record = runs.get(project, run)
        if record["adapter"] != "robot_motion" or record["status"] != "completed":
            raise HTTPException(409, "Joint-frame replay requires a completed robot motion run")
        evidence(record)
        try:
            model = record["result"]["model"]
            if model.get("asset_id"):
                identifier = record["inputs"].get("model_asset_id")
                if identifier != model["asset_id"] or not any(a["id"] == identifier for a in record["snapshot"]["assets"]):
                    raise ValueError("No matching URDF in the recorded revision")
                _, path = runs.projects.asset(project, identifier)
                model_bytes = path.read_bytes()
            elif model.get("reference_id") == "two_finger_hand_v1":
                model_bytes = HAND_URDF
            else:
                raise ValueError("No identified model for this recording")
            return link_trajectories(record["result"], model_bytes)
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(409, f"Recorded link geometry unavailable: {error}") from error
    return router
