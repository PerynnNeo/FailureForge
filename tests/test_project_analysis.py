import json
import io
import math
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.artifacts import ArtifactError
from failureforge.project_bundle import inspect_project_bundle
from failureforge.project_inputs import CadInventory, inspect_cad
from failureforge.project_runs import compare, outcome


def wait(client, url):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        body = client.get(url).json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.05)
    pytest.fail("project analysis did not finish")


def test_legacy_failed_qualification_never_counts_as_observed_failure():
    def record(identifier):
        return {"id": identifier, "label": "same task", "project_revision": 1, "adapter": "robot_motion",
                "status": "completed", "evidence_hash": identifier, "runtime": {}, "inputs": {},
                "snapshot": {"analysis_type": "robot_behavior", "success_criteria": "Reach the target"},
                "result": {"passed": True, "model": {"root_link": "palm", "tip_link": "tip", "joints": [
                    {"name": "j", "parent": "palm", "child": "tip", "type": "revolute", "unit": "rad", "axis_in_joint_frame": [0, 0, 1]}]}}}
    baseline, candidate = record("r1"), record("r2")
    candidate["result"].update(passed=False, dynamics={"reference_qualification": [{"task": "hold_initial", "passed": False}]})
    assert outcome(candidate) is None
    comparison = compare(baseline, candidate)
    assert comparison["outcome"] == "not_comparable" and any("qualification" in r for r in comparison["reasons"])
    candidate["result"]["dynamics"] = None
    candidate["result"]["model"]["joints"][0]["mimic"] = {"source": "other", "multiplier": -1, "offset": 0}
    assert compare(baseline, candidate)["outcome"] == "not_comparable"


def project(client, analysis):
    data = {"name": "revision test", "entry_stage": "prototype", "analysis_type": analysis,
            "goal": "Evaluate response", "success_criteria": "Meet the declared limit"}
    response = client.post("/api/projects", json=data)
    assert response.status_code == 201
    return "/api/projects/" + response.json()["id"], data


def test_suite_regression_and_idempotent_recovery(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        url, draft = project(client, "thermal")
        example = next(a["example"] for a in client.get(url+"/analysis").json()["adapters"] if a["id"] == "thermal_rod")
        case = {"label": "cooling", "adapter": "thermal_rod", "inputs": {**example, "max_temperature_k": 310.0}}
        suite = {"expected_revision": 1, "tests": [case, {**case, "inputs": {**example, "length_m": -7}}]}
        key = {"Idempotency-Key": "repeat-this-suite"}
        first = client.post(url+"/analysis-suite", headers=key, json=suite)
        assert first.status_code == 202, first.text
        ids = [r["id"] for r in first.json()["runs"]]
        repeated = client.post(url+"/analysis-suite", headers=key, json=suite)
        assert ids == [r["id"] for r in repeated.json()["runs"]]
        baseline = wait(client, url+"/analysis/"+ids[0])
        assert baseline["status"] == "completed" and baseline["result"]["passed"]
        assert wait(client, url+"/analysis/"+ids[1])["status"] == "invalid"
        assert client.post(url, json={**draft, "expected_revision": 1, "notes": "revised material"}).status_code == 200
        revised = {**case, "inputs": {**case["inputs"], "conductivity_w_mk": 0.1}}
        assert client.post(url+"/analysis", json={**revised, "expected_revision": 1}).status_code == 409
        new = client.post(url+"/analysis", json={**revised, "expected_revision": 2}).json()["id"]
        alternate = wait(client, url+"/analysis/"+new)
        assert alternate["status"] == "completed" and not alternate["result"]["passed"]
        report = client.get(f"{url}/analysis/{ids[0]}/compare/{new}").json()
        assert report["comparable"] and report["outcome"] == "new_failure"
        assert report["changed_inputs"].keys() == {"conductivity_w_mk"}
        assert baseline["snapshot"]["revision"] == 1
        other, _ = project(client, "thermal")
        assert client.get(f"{other}/analysis/{new}").status_code == 404
    with TestClient(create_app(tmp_path)) as restarted:
        assert restarted.get(f"{url}/analysis/{new}").json()["evidence_hash"] == alternate["evidence_hash"]


def test_heldout_joint_fit_and_promotion(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        url, _ = project(client, "robot_behavior")
        def log(label, target):
            rows = ["time_s,command_rad,position_rad"]
            for i in range(30):
                t = 0.05*i
                rows.append(f"{t},{target},{target*(1-math.exp(-t/0.21))}")
            data = client.post(url+"/assets", params={"filename": label+".csv", "kind": "measurements"},
                               content="\n".join(rows), headers={"Content-Type": "application/octet-stream"})
            assert data.status_code == 201
            return next(a["id"] for a in data.json()["assets"] if a["filename"] == label+".csv")
        training, validation = log("fit", 0.5), log("holdout", -0.3)
        inputs = {"joint_name": "pivot", "hardware_revision": "fixture-v1", "training_asset_id": training,
                  "validation_asset_id": validation, "max_validation_rmse_rad": 0.005}
        run = client.post(url+"/analysis", json={"expected_revision": 3, "label": "identification",
                          "adapter": "joint_response", "inputs": inputs}).json()
        detail = wait(client, f"{url}/analysis/{run['id']}")
        assert detail["result"]["passed"]
        assert detail["result"]["summary"]["time_constant_s"] == pytest.approx(0.21, rel=1e-6)
        package = client.get(f"{url}/analysis/{run['id']}/bundle")
        assert package.status_code == 200
        archive = tmp_path/"calibration.zip"
        archive.write_bytes(package.content)
        verify = inspect_project_bundle(archive, rerun=True)
        assert verify["rerun"]["exact_result_match"]
        assert set(verify["resources"]) == {"fit.csv", "holdout.csv"}
        with zipfile.ZipFile(io.BytesIO(package.content)) as source, zipfile.ZipFile(tmp_path/"altered.zip", "w") as modified:
            for name in source.namelist():
                modified.writestr(name, b"changed" if name.startswith("assets/") else source.read(name))
        with pytest.raises(ArtifactError, match="checksum"):
            inspect_project_bundle(tmp_path/"altered.zip")
        promoted = client.post(f"{url}/analysis/{run['id']}/promote", json={"expected_revision": 3})
        assert promoted.status_code == 200 and promoted.json()["revision"] == 4
        assert detail["evidence_hash"] in promoted.json()["parameters"][0]["evidence"]
        assert client.post(f"{url}/analysis/{run['id']}/promote", json={"expected_revision": 3}).status_code == 409


def test_cad_component_inventory_and_bom():
    cad = CadInventory(cad_asset_id="asset_"+"a"*32, units="mm", component="bracket")
    mesh = b"solid part\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 100 0 0\nvertex 0 100 0\nendloop\nendfacet\nendsolid part"
    result = inspect_cad(cad, mesh, b"component,material,source\nbracket,alloy,datasheet")
    assert result["summary"]["surface_area_m2"] == pytest.approx(0.005)
    assert result["material_assignment"]["source"] == "datasheet"
    assert len(result["preview_triangles_m"]) == 1
    with pytest.raises(ValueError, match="matching"):
        inspect_cad(cad, mesh, b"component,material,source\nhousing,alloy,datasheet")


def test_comparison_matches_named_robot_joint_frames_and_resolved_links():
    from copy import deepcopy

    joints = [{"name": n, "type": "revolute", "unit": "rad", "parent": "palm", "child": n+"_tip",
               "axis_in_joint_frame": [0, 0, 1]} for n in ("finger_1", "finger_2")]
    baseline = {"id": "before", "label": "joints", "adapter": "robot_motion", "inputs": {},
                "project_revision": 1, "status": "completed", "runtime": {}, "evidence_hash": "baseline",
                "snapshot": {"analysis_type": "robot_behavior", "success_criteria": "track target"},
                "result": {"passed": True, "model": {"root_link": "palm", "tip_link": "finger_1_tip", "joints": joints}}}
    candidate = deepcopy(baseline)
    candidate["id"] = "after"
    candidate["result"]["model"]["joints"].reverse()
    assert compare(baseline, candidate)["outcome"] == "unchanged_pass"
    for key, value in (("unit", "m"), ("axis_in_joint_frame", [1, 0, 0]), ("parent", "wrist"), ("child", "new_link")):
        changed = deepcopy(candidate)
        changed["result"]["model"]["joints"][0][key] = value
        assert compare(baseline, changed)["outcome"] == "not_comparable"
    for key in ("root_link", "tip_link"):
        changed = deepcopy(candidate)
        changed["result"]["model"][key] = "different"
        assert compare(baseline, changed)["outcome"] == "not_comparable"
    del candidate["result"]["model"]["joints"][0]["axis_in_joint_frame"]
    assert compare(baseline, candidate)["outcome"] == "not_comparable"
