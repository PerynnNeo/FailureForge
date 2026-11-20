import json
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from failureforge.api import create_app
from failureforge.environment_matrices import EnvironmentMatrix, _report
from failureforge.project_bundle import inspect_project_bundle


SPEC = {"expected_revision": 1, "label": "Lift at pack station", "adapter": "packaging_lift",
        "payload_kg": [0, 0.5], "head_force_n": [0, 2], "reference": {"payload_kg": 0, "head_force_n": 0}}
PROJECT = {"name": "Fixture lift", "analysis_type": "robot_behavior", "entry_stage": "prototype",
           "robot_source": "supported", "robot_template": "packaging_lift_v1",
           "goal": "Hold the parcel at the packing station", "success_criteria": "Hold the declared position"}


def test_persisted_environment_matrix_pairs_project_runs_with_the_declared_conditions(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project = "/api/projects/" + client.post("/api/projects", json=PROJECT).json()["id"]
        path = project + "/environment-matrices"
        headers = {"Idempotency-Key": "fixed-load-matrix-v1"}
        assert "packaging_lift" in {a["id"] for a in client.get(project + "/analysis").json()["adapters"]}
        assert client.post(path, json={**SPEC, "head_force_n": [0, 6]}, headers=headers).status_code == 422
        assert client.get(path).json() == {"matrices": []}
        assert client.get(project + "/analysis").json()["runs"] == []
        response = client.post(path, json=SPEC, headers=headers)
        assert response.status_code == 202, response.text
        receipt = response.json()
        suite = receipt["suite_id"]
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            report = client.get(path + "/" + suite).json()
            if report["status"] != "running":
                break
            time.sleep(0.1)
        assert report["status"] == "completed", report
        assert report["counts"]["passed"] + report["counts"]["failed"] == 4
        assert report["reference_passed"] is True
        assert [(c["payload_kg"], c["head_force_n"]) for c in report["cells"]] == [(0, 0), (0, 2), (0.5, 0), (0.5, 2)]
        hashes = set()
        for cell in report["cells"]:
            run = client.get(project + "/analysis/" + cell["run_id"]).json()
            assert run["result"]["passed"] == cell["passed"]
            assert run["inputs"] == {"payload_kg": cell["payload_kg"], "head_force_n": cell["head_force_n"]}
            assert run["project_revision"] == 1
            assert cell["evidence_hash"] == run["evidence_hash"] and len(cell["evidence_hash"]) == 64
            assert cell["metrics"] == run["result"]["summary"]
            assert client.get(cell["bundle_url"]).status_code == 200
            hashes.add(json.dumps(run["runtime"], sort_keys=True))
        assert len(hashes) == 1
        assert report["cells"][-1]["passed"] is False
        assert client.get(path).json()["matrices"][0]["suite_id"] == suite
        assert client.get(project + "/sweeps").json() == {"sweeps": []}
        assert client.get(project + "/sweeps/" + suite).status_code == 404
        other = client.post("/api/projects", json={**PROJECT, "analysis_type": "thermal"}).json()["id"]
        other_path = f"/api/projects/{other}/environment-matrices"
        assert client.get(other_path + "/" + suite).status_code == 404
        assert client.post(other_path, json=SPEC).status_code == 422
        assert client.get(other_path).json() == {"matrices": []}
        assert client.post(path, json={**SPEC, "head_force_n": [0, 1]}, headers=headers).status_code == 409
        assert client.post(project, json={**PROJECT, "expected_revision": 1,
                                          "robot_source": "custom", "robot_template": None}).status_code == 200
        assert client.post(path, json=SPEC, headers=headers).json()["suite_id"] == suite
        assert client.post(path, json=SPEC).status_code == 409
        assert client.post(path, json={**SPEC, "expected_revision": 2}).status_code == 422
        assert len(client.get(project + "/analysis").json()["runs"]) == 4
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(path + "/" + suite).json() == report


@pytest.mark.parametrize("source,template", [("custom", None), ("supported", "two_finger_hand_v1")])
def test_fixture_specific_analysis_requires_matching_robot_template(tmp_path, source, template):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/projects", json={**PROJECT, "robot_source": source, "robot_template": template})
        assert response.status_code == 201
        project = "/api/projects/" + response.json()["id"]
        catalog = client.get(project + "/analysis").json()["adapters"]
        assert {"packaging_lift", "packaging_lift_timed_v2"}.isdisjoint(a["id"] for a in catalog)
        single = {"expected_revision": 1, "label": "Fixture", "adapter": "packaging_lift",
                  "inputs": {"payload_kg": 0, "head_force_n": 0}}
        assert client.post(project + "/analysis", json=single).status_code == 422
        assert client.post(project + "/environment-matrices", json=SPEC).status_code == 422
        assert client.get(project + "/analysis").json()["runs"] == []
        assert client.get(project + "/environment-matrices").json() == {"matrices": []}


def test_timed_case_preserves_measured_pulse_in_portable_rerun(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        owner = client.post("/api/projects", json=PROJECT).json()["id"]
        path = f"/api/projects/{owner}/analysis"
        inputs = {"payload_kg": 0.5, "head_force_n": 2, "head_onset_ms": 751, "head_duration_ms": 1000}
        queued = client.post(path, json={"expected_revision": 1, "label": "Early press",
                             "adapter": "packaging_lift_timed_v2", "inputs": inputs})
        assert queued.status_code == 202, queued.text
        case_path = path + "/" + queued.json()["id"]
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            record = client.get(case_path).json()
            if record["status"] not in {"queued", "running"}:
                break
            time.sleep(0.1)
        assert record["status"] == "completed" and not record["assessment_error"]
        assert record["result"]["criteria"]["arrived_within_tolerance"] is False
        assert record["result"]["force_schedule"]["requested"]["head_onset_ms"] == 751
        assert client.get(case_path + "/hardware-trials").json()["metrics"] == {}
        bundle = client.get(case_path + "/bundle")
        assert bundle.status_code == 200
        archive = tmp_path / "timed-lift.zip"
        archive.write_bytes(bundle.content)
        report = inspect_project_bundle(archive, rerun=True)
        assert report["rerun"]["exact_result_match"] and report["rerun"]["same_runtime_identity"]


@pytest.mark.parametrize("changes", [
    {"payload_kg": [0, 1, 2, 3], "head_force_n": [0, 1, 2, 3, 4]},
    {"payload_kg": [0, 0]}, {"head_force_n": [2, 0]}, {"head_force_n": [0]},
    {"reference": {"payload_kg": 0.25, "head_force_n": 0}}, {"payload_kg": [0, float("inf")]},
    {"head_force_n": [False, 1]}, {"payload_kg": [-1, 0]}, {"adapter": "robot_motion"},
    {"time_limit": 10}, {"reference": {"payload_kg": 0}},
])
def test_matrix_rejects_invalid_or_unbounded_grids(changes):
    with pytest.raises(ValidationError):
        EnvironmentMatrix.model_validate({**SPEC, **changes})


def test_matrix_preserves_missing_and_blocked_evidence_without_shifting_cell_positions():
    spec = EnvironmentMatrix.model_validate(SPEC)
    def row(n, mass, force, **updates):
        return {"id": f"run_{n}", "ordinal": n, "runtime": "build1", "status": "completed", "diagnostics_passed": 1,
                "inputs": json.dumps({"payload_kg": mass, "head_force_n": force}),
                "evidence_hash": "a"*64, "error": None, "metrics": "{}", "passed": 1, **updates}
    rows = [row(0, 0, 0), row(2, 0.5, 0, diagnostics_passed=0), row(3, 0.5, 2, runtime="build2", passed=0)]
    report = _report("p", spec.model_dump(), rows)
    assert report["status"] == "partial" and report["reference_passed"] is True
    assert report["counts"] == {"total": 4, "pending": 0, "passed": 1, "failed": 0, "blocked": 3}
    missing, diagnostic, different_runtime = report["cells"][1:]
    assert missing["status"] == "missing" and missing["run_id"] is None and missing["bundle_url"] is None
    assert diagnostic["passed"] is None and "numerical" in diagnostic["error"]
    assert different_runtime["passed"] is None and "runtime" in different_runtime["error"]
