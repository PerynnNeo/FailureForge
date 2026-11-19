import json
import time

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.project_solver import BEAM
from failureforge.project_sweeps import Sweep, _plan, _summarize


def _wait(client, url):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] != "running":
            return body
        time.sleep(0.1)
    pytest.fail("Sweep did not finish")


def _project(client, kind, **extra):
    inputs = {"name": "Sweep reference", "analysis_type": kind, "entry_stage": "concept", "goal": "Apply bounded conditions",
              "success_criteria": "Pass the selected input's engineering and task limits", **extra}
    response = client.post("/api/projects", json=inputs)
    assert response.status_code == 201
    return "/api/projects/" + response.json()["id"], inputs


def test_complete_bound_suite_remains_reproducible_and_selects_measured_failure(tmp_path):
    params = [{"name": "Material stiffness", "value": "70", "unit": "GPa", "source": "supplier"}]
    with TestClient(create_app(tmp_path)) as client:
        project, design = _project(client, "structural", parameters=params)
        url = project + "/sweeps"
        available = client.get(url + "/catalog").json()
        assert available["max_points"] == 16 and set(available["adapters"]) == {"structural_beam"}
        base = {**BEAM, "tip_force_n": 0, "max_displacement_m": 1e-6}
        del base["young_modulus_pa"]
        spec = {"expected_revision": 1, "adapter": "structural_beam", "label": "Signed load", "field": "tip_force_n",
                "inputs": base, "bindings": {"young_modulus_pa": "Material stiffness"}, "values": [-10, 0, 10]}
        headers = {"Idempotency-Key": "replay-the-sweep"}
        started = client.post(url, json=spec, headers=headers)
        assert started.status_code == 202, started.text
        suite = started.json()["suite_id"]
        report = _wait(client, url + "/" + suite)
        assert report["status"] == "completed" and report["reference_passed"] is True
        assert report["counts"] == {"total": 3, "measured": 3, "failed": 2, "passed": 1, "pending": 0,
                                     "blocked": 0, "measurement_only": 0}
        assert report["nearest_observed_failure"]["value"] == -10
        assert [p["value"] for p in report["points"]] == [-10, 0, 10]
        for point in report["points"]:
            run = client.get(project + "/analysis/" + point["run_id"]).json()
            assert run["project_revision"] == 1 and run["inputs"]["young_modulus_pa"] == 70e9
            assert run["inputs"]["tip_force_n"] == point["value"]
            assert run["binding_evidence"]["young_modulus_pa"]["source_unit"] == "GPa"
        assert client.post(project, json={**design, "expected_revision": 1, "parameters": []}).status_code == 200
        replay = client.post(url, json=spec, headers=headers)
        assert replay.status_code == 202 and replay.json()["suite_id"] == suite
        assert client.post(url, json=spec).status_code == 409
        assert client.get(url).json()["sweeps"][0]["suite_id"] == suite
        other, _ = _project(client, "structural")
        assert client.get(other + "/sweeps/" + suite).status_code == 404
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(url + "/" + suite).json() == report


def test_robot_target_preserves_other_joints_and_keeps_invalid_points_blocked(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project, _ = _project(client, "robot_behavior")
        url = project + "/sweeps"
        spec = {"expected_revision": 1, "label": "Joint commands", "adapter": "robot_motion", "field": "targets.left_knuckle",
                "inputs": {"targets": {"left_knuckle": 0.0, "right_knuckle": 0.01}, "duration_s": 0.02},
                "values": [-0.45, 0, 1]}
        result = client.post(url, json=spec)
        assert result.status_code == 202, result.text
        report = _wait(client, url + "/" + result.json()["suite_id"])
        assert report["status"] == "partial" and report["reference_passed"] is True
        assert report["counts"]["measured"] == 2 and report["counts"]["blocked"] == 1
        assert report["nearest_observed_failure"]["value"] == -0.45
        assert report["points"][-1]["passed"] is None and report["points"][-1]["status"] == "invalid"
        for point in report["points"]:
            run = client.get(project + "/analysis/" + point["run_id"]).json()
            assert run["inputs"]["targets"]["right_knuckle"] == 0.01


@pytest.mark.parametrize("delta,reason", [
    ({"values": [0.0, 0.0]}, "increase"),
    ({"values": [1, 0]}, "increase"),
    ({"values": [-2, -1]}, "reference"),
    ({"field": "max_displacement_m"}, "physical inputs"),
    ({"field": "young_modulus_pa", "values": [0, 70e9]}, "greater than or equal"),
    ({"bindings": {"tip_force_n": "Load"}}, "literal reference"),
])
def test_invalid_grid_rejected_before_any_run(delta, reason):
    spec = Sweep.model_validate({"expected_revision": 1, "label": "grid", "adapter": "structural_beam", "field": "tip_force_n",
                                 "inputs": {**BEAM, "tip_force_n": 0}, "values": [0, 5], **delta})
    with pytest.raises(ValueError, match=reason):
        _plan(spec, {"analysis_type": "structural", "parameters": [], "revision": 1})


def test_pending_and_unqualified_points_do_not_become_failures():
    definition = {"values": [0, 1, 2, 3, 4], "reference_value": 1}
    def row(index, status, passed, **extra):
        return {"id": str(index), "status": status, "passed": passed, "error": None, "runtime": "v1",
                "metrics": "{}", "diagnostics_passed": None, "qualification": None, **extra}
    rows = [row(0, "queued", None), row(1, "completed", None),
            row(2, "completed", 0, diagnostics_passed=0),
            row(3, "completed", 0, qualification=json.dumps([{"passed": False}])),
            row(4, "completed", 0, runtime="v2")]
    report = _summarize("s", definition, rows)
    assert report["status"] == "running" and report["reference_passed"] is None
    assert report["nearest_observed_failure"] is None
    assert report["counts"] == {"total": 5, "measured": 4, "measurement_only": 1, "blocked": 3,
                                "pending": 1, "passed": 0, "failed": 0}


def test_request_bounds_and_finite_coordinates():
    base = {"expected_revision": 1, "label": "grid", "adapter": "thermal_rod", "field": "heat_generation_w_m3", "inputs": {}}
    for invalid in ([0], list(range(17)), [0, float("nan")], [0, float("inf")], [False, 1]):
        with pytest.raises(ValueError):
            Sweep.model_validate({**base, "values": invalid})
