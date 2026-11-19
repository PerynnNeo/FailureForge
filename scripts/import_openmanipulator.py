"""Verify the pinned public physical logs and submit their declared fit to a local workbench."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "openmanipulator-x"
TITLE = "OpenManipulator-X · physical joint 1 sweep (NAD)"
BASE = "http://127.0.0.1:8000/api/projects"


def sha256(contents):
    return hashlib.sha256(contents).hexdigest()


def verify(name, expected):
    data = (FIXTURE / name).read_bytes()
    if sha256(data) != expected:
        raise ValueError(f"Original file hash mismatch: {name}")
    return data


def prepare(provenance):
    outcomes = {}
    for split, trial in provenance["trials"].items():
        source = verify(f"{split}-001-raw.csv", trial["sha256"])
        records = csv.DictReader(io.StringIO(source.decode("utf-8-sig")))
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        columns = provenance["projection"]
        writer.writerow(columns.keys())
        prior = -math.inf
        count = 0
        for row in records:
            values = [row[name] for name in columns.values()]
            stamp, command, position = map(float, values)
            if not all(map(math.isfinite, (stamp, command, position))) or stamp <= prior:
                raise ValueError(f"{split} has invalid or unordered samples")
            prior = stamp
            writer.writerow(values)
            count += 1
        path = FIXTURE / f"{split}-joint1.csv"
        contents = output.getvalue().encode()
        if not path.exists() or path.read_bytes() != contents:
            path.write_bytes(contents)
        outcomes[split] = {"rows": count, "projected_sha256": sha256(contents)}
    verify("open_manipulator_x.urdf", provenance["model"]["sha256"])
    for name, record in provenance["licenses"].items():
        verify(name, record["sha256"])
    return outcomes


def api(path="", data=None, *, binary=False, key=None):
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/octet-stream" if binary else "application/json"
        if not binary:
            data = json.dumps(data, allow_nan=False).encode()
    if key is not None:
        headers["Idempotency-Key"] = key
    req = Request(BASE + path, data=data, headers=headers)
    try:
        with urlopen(req, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Workbench returned HTTP {exc.code}: {exc.read(1000).decode()}") from exc


def run_analysis(project, key, label, adapter, inputs):
    path = "/" + project["id"] + "/analysis"
    run = api(path, {"expected_revision": project["revision"], "label": label, "adapter": adapter, "inputs": inputs},
              key=f"{key}-revision-{project['revision']}")
    deadline = time.monotonic() + 100
    while run["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.4)
        run = api(f"{path}/{run['id']}")
    result = run.get("result") or {}
    return {"run_id": run["id"], "status": run["status"], "error": run.get("error"), "passed": result.get("passed"),
            "summary": result.get("summary", result.get("metrics")), "evidence_hash": run.get("evidence_hash")}


def submit(provenance):
    project_spec = {"name": TITLE, "entry_stage": "prototype", "analysis_type": "robot_behavior",
                    "goal": "Fit a one-joint position-response time constant to public measurements from an OpenManipulator-X follower.",
                    "success_criteria": "Whole-trajectory held-out RMSE at most 0.02 radians, excluding the initialized first sample.",
                    "notes": "Original physical measurements are from Dou et al. (RSS 2026). Test and training are separate repetitions of the same task. The manufacturer model identifies the hardware family."}
    matches = [p for p in api()["items"] if p["name"] == TITLE and p["goal"] == project_spec["goal"]]
    if len(matches) > 1:
        raise ValueError("More than one project matches the physical reference study")
    project = matches[0] if matches else api(data=project_spec)
    path = "/" + project["id"]
    assets = {}
    files = {"train-001-raw.csv": "measurements", "test-001-raw.csv": "measurements",
             "train-joint1.csv": "measurements", "test-joint1.csv": "measurements",
             "open_manipulator_x.urdf": "robot_model", "provenance.json": "requirements",
             **{name: "requirements" for name in provenance["licenses"]}}
    for name, kind in files.items():
        data = (FIXTURE / name).read_bytes()
        matching = [a for a in project["assets"] if a["filename"] == name and a["kind"] == kind and a["sha256"] == sha256(data)]
        if not matching:
            query = urlencode({"kind": kind, "filename": name})
            project = api(f"{path}/assets?{query}", data, binary=True)
            matching = [a for a in project["assets"] if a["filename"] == name and a["sha256"] == sha256(data)]
        assets[name] = matching[0]["id"]
    inputs = {**provenance["acceptance"], "joint_name": "joint1 / Dynamixel ID 11",
              "hardware_revision": "NAD OpenManipulator-X follower, Dynamixel XM430-W350; individual serial/revision unreported",
              "training_asset_id": assets["train-joint1.csv"], "validation_asset_id": assets["test-joint1.csv"]}
    calibration = run_analysis(project, "nad-motor11-study-v1", "NAD physical held-out joint 1 response", "joint_response", inputs)
    movement = {"model_asset_id": assets["open_manipulator_x.urdf"], "mode": "prescribed",
                "targets": {"joint1": 0.35, "gripper_left_joint": 0.005}, "tip_link": "end_effector_link",
                "samples": 101, "duration_s": 2, "tolerance": 0.001}
    motion = run_analysis(project, "omx-urdf-motion-v1", "Manufacturer URDF arm and coupled gripper motion", "robot_motion", movement)
    # The manufacturer's 4.8 rad/s base-joint limit is checked over the same short linear motion at each point.
    sweep = {"expected_revision": project["revision"], "label": "Manufacturer URDF base-joint speed sweep",
             "adapter": "robot_motion", "inputs": {**movement, "duration_s": 0.05,
                         "targets": {"joint1": 0.12, "gripper_left_joint": 0.005}},
             "field": "targets.joint1", "values": [0.0, 0.12, 0.25, 0.35, 0.55]}
    grid = api(path + "/sweeps", sweep, key=f"omx-base-joint-speed-grid-v1-revision-{project['revision']}")
    deadline = time.monotonic() + 100
    while grid["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.4)
        grid = api(path + "/sweeps/" + grid["suite_id"])
    summary = {key: grid[key] for key in ("suite_id", "status", "reference_passed", "counts")}
    summary["points"] = [{"target_rad": point["value"], "passed": point["passed"], "run_id": point["run_id"],
                          "peak_speed_rad_s": point["metrics"].get("peak_joint_speed", {}).get("joint1"), "error": point["error"]}
                         for point in grid["points"]]
    nearest = grid["nearest_observed_failure"]
    summary["nearest_failing_target_rad"] = nearest["value"] if nearest else None
    return {"project_id": project["id"], "calibration": calibration, "kinematics": motion, "kinematic_sweep": summary}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true", help="Create or reuse the example project on the local workbench and run its fit")
    args = parser.parse_args()
    metadata = json.loads((FIXTURE / "provenance.json").read_text(encoding="utf-8"))
    report = {"prepared": prepare(metadata)}
    if args.submit:
        report["run"] = submit(metadata)
    print(json.dumps(report, indent=2, allow_nan=False))
    if args.submit and any(report["run"][key]["status"] != "completed" for key in ("calibration", "kinematics", "kinematic_sweep")):
        raise SystemExit(1)
