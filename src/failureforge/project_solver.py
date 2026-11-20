"""Allowlisted project analyses. Each invocation handles one immutable job."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path

from .engineering import BeamStudy, CalibrationStudy, ThermalStudy, run_engineering
from .packaging_lift import LIFT_ADAPTERS, PackagingLift, TimedPackagingLift, run_packaging_lift
from .project_inputs import CadInventory, JointResponse, fit_joint_response, inspect_cad
from .project_robot import RobotRunRequest, robot_reference, run_robot


BEAM = {"kind": "structural_beam", "length_m": 0.2, "width_m": 0.02, "height_m": 0.01,
        "young_modulus_pa": 70e9, "tip_force_n": 5, "distributed_load_n_per_m": 0, "elements": 16}
ROD = {"kind": "thermal_rod", "length_m": 0.1, "area_m2": 0.0004, "conductivity_w_mk": 15,
       "left_temperature_k": 293.15, "right_temperature_k": 303.15, "heat_generation_w_m3": 12000, "elements": 16}
ASSET_FIELDS = {"cad_asset_id": ("cad", ".stl"), "bom_asset_id": ("bom", ".csv"),
                "training_asset_id": ("measurements", ".csv"), "validation_asset_id": ("measurements", ".csv"),
                "model_asset_id": ("robot_model", ".urdf"), "controller_asset_id": ("controller", ".json")}
MODELS = {"structural_beam": BeamStudy, "thermal_rod": ThermalStudy, "calibration": CalibrationStudy,
          "joint_response": JointResponse, "cad_inventory": CadInventory, "robot_motion": RobotRunRequest,
          "packaging_lift": PackagingLift, "packaging_lift_timed_v2": TimedPackagingLift}
PLACEHOLDER = "asset_" + "0" * 32


def adapters(analysis):
    entries = []
    def add(key, label, description, example):
        entries.append({"id": key, "label": label, "description": description,
                        "example": example, "schema": MODELS[key].model_json_schema()})
    if analysis == "robot_behavior":
        add("robot_motion", "Articulated motion", "Track named joint targets on the reference hand or a supported robot description.",
            robot_reference()["example"])
        entries[-1]["reference"] = robot_reference()
        add("packaging_lift", "Packaging lift", "Test the fixed vertical lift under a secured parcel and a downward packing-head force.",
            {"payload_kg": 0.0, "head_force_n": 0.0})
        add("packaging_lift_timed_v2", "Packaging lift with timed press",
            "Place a finite downward head-force pulse during the two-second lift cycle. Measure arrival and hold separately.",
            {"payload_kg": 0.5, "head_force_n": 2.0, "head_onset_ms": 1000, "head_duration_ms": 1000})
        add("joint_response", "Calibrate joint response", "Fit one time constant against a training log and test it on another. Supply CSV columns time_s,command_rad,position_rad.",
            {"joint_name": "left_knuckle", "hardware_revision": "enter measured revision",
             "training_asset_id": PLACEHOLDER, "validation_asset_id": "asset_" + "1"*32, "max_validation_rmse_rad": 0.02})
    else:
        beam = analysis == "structural"
        model = BEAM if beam else ROD
        add(model["kind"], "Cantilever bending" if beam else "Steady rod conduction",
            "Static bending of a rectangular cantilever under signed point loads, distributed loads over specified spans and uniform face pressure." if beam else
            "Steady heating of a uniform rod with a fixed left end and either a fixed or convective right end.", model)
        add("calibration", "Calibrate material property", "Enter measurements from distinct fit and validation runs. Values in the example are illustrative.",
            {"kind": "calibration", "model": model, "parameter_bounds": [1e9, 2e11] if beam else [0.1, 1000],
             "validation_tolerance": 0.0001 if beam else 1.0,
             "fit": [{"run_id": "example-fit", **({"tip_force_n": 5, "tip_displacement_m": 0.000115}
                     if beam else {"heat_generation_w_m3": 12000, "position_m": 0.05, "temperature_k": 299.15})}],
             "validation": [{"run_id": "example-validation", **({"tip_force_n": 3, "tip_displacement_m": 0.000069}
                     if beam else {"heat_generation_w_m3": 6000, "position_m": 0.05, "temperature_k": 298.65})}]})
    add("cad_inventory", "Inspect CAD and bill of materials", "Inspect one STL in declared units and optionally match a BOM CSV row (component,material,source).",
        {"cad_asset_id": PLACEHOLDER, "units": "mm", "component": "bracket"})
    return entries


def run_job(job):
    adapter = job["adapter"]
    raw = job["inputs"].copy()
    if adapter in ("structural_beam", "thermal_rod", "calibration"):
        raw.setdefault("kind", adapter)
    model = MODELS[adapter].model_validate(raw)
    if adapter == "calibration" and model.model.kind != {"structural": "structural_beam", "thermal": "thermal_rod"}.get(job["analysis_type"]):
        raise ValueError("Calibration fixture must match the project's analysis")
    blobs = {}
    for field, (kind, suffix) in ASSET_FIELDS.items():
        identifier = getattr(model, field, None)
        if identifier is None:
            continue
        asset = job["assets"].get(identifier)
        if asset is None or asset["kind"] != kind or Path(asset["filename"]).suffix.lower() != suffix:
            raise ValueError(f"{field} must reference a project {kind} file with extension {suffix}")
        data = Path(asset["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise OSError(f"Stored {field} changed after the revision snapshot")
        blobs[field] = data
    if adapter == "cad_inventory":
        result = inspect_cad(model, blobs["cad_asset_id"], blobs.get("bom_asset_id"))
    elif adapter == "joint_response":
        result = fit_joint_response(model, blobs["training_asset_id"], blobs["validation_asset_id"])
    elif adapter == "robot_motion":
        result = run_robot(model, blobs.get("model_asset_id"), blobs.get("controller_asset_id"))
    elif adapter in LIFT_ADAPTERS:
        if job["analysis_type"] != "robot_behavior":
            raise ValueError("The packaging lift requires a robot behavior project")
        result = run_packaging_lift(model)
    else:
        result = run_engineering(model.model_dump())
    return result


def runtime_identity(adapter=None):
    from . import beam_span, engineering, packaging_lift, project_inputs, project_robot, robot_dynamics, urdf_mjcf
    versions = {}
    for name in ("numpy", "scipy", "mujoco", "pydantic"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    sources = [__file__, engineering.__file__, project_inputs.__file__, project_robot.__file__,
               robot_dynamics.__file__, urdf_mjcf.__file__]
    if adapter in LIFT_ADAPTERS:
        sources.append(packaging_lift.__file__)
    if adapter in ("structural_beam", "calibration"):
        sources.append(beam_span.__file__)
    return {"python": platform.python_version(), "packages": versions, "source_sha256": {
        Path(file).name: hashlib.sha256(Path(file).read_bytes()).hexdigest()
        for file in sources}}


def main():
    try:
        job = json.load(sys.stdin)
        result = run_job(job)
        response = {"status": "completed", "result": result, "runtime": runtime_identity(job["adapter"])}
    except (ValueError, UnicodeError) as exc:
        response = {"status": "invalid", "error": str(exc)[:2000]}
    except Exception as exc:
        response = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:2000]}
    # Native libraries may write diagnostics to stdout; publish through a dedicated file.
    with open(os.environ["FAILUREFORGE_SOLVER_OUTPUT"], "x", encoding="utf-8") as stream:
        json.dump(response, stream, allow_nan=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
