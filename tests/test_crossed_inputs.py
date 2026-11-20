from itertools import product
import time

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.crossed_inputs import CrossedCampaign, crossed_tests
from failureforge.project_solver import BEAM, ROD


PROJECT = {"name": "Bracket", "entry_stage": "concept", "analysis_type": "structural",
           "goal": "Measure bending", "success_criteria": "Hold target deflection"}
AXES = [{"field": "tip_force_n", "values": [-5, 5]}, {"field": "face_pressure_pa", "values": [0, 5000]}]


def test_two_load_campaign_runs_atomically_and_retries_on_immutable_revision(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    project = client.post("/api/projects", json=PROJECT).json()["id"]
    base = "/api/project-campaigns/" + project
    headers = {"Idempotency-Key": "two-loads-test"}
    spec = {"expected_revision": 1, "adapter": "structural_beam", "label": "Tip load under face pressure",
            "inputs": {**BEAM, "face_pressure_pa": 0}, "axes": AXES}
    # Length of 0.05 m is incompatible with the reference bending depth, even though other cells are valid.
    invalid = {**spec, "axes": [AXES[0], {"field": "length_m", "values": [0.05, 0.2]}]}
    assert client.post(base + "/crossed", json=invalid).status_code == 422
    assert client.get(f"/api/projects/{project}/analysis").json()["runs"] == []
    submit = client.post(base + "/crossed", json=spec, headers=headers)
    assert submit.status_code == 202, submit.text
    suite = submit.json()["suite_id"]
    detail = client.get(base + "/" + suite).json()
    assert detail["kind"] == "suite" and detail["label"] == spec["label"]
    assert len(detail["runs"]) == 4
    assert detail["runs"][0]["coordinates"] == {"tip_force_n": 5, "face_pressure_pa": 0}
    assert detail["runs"][0]["label"].endswith("reference")
    assert detail["runs"][0]["reference"] and sum(row["reference"] for row in detail["runs"]) == 1
    assert detail["crossed_design"]["axes"] == AXES
    assert {(r["coordinates"]["tip_force_n"], r["coordinates"]["face_pressure_pa"]) for r in detail["runs"]} == set(product([-5, 5], [0, 5000]))
    assert client.get(base + "/" + suite + "/coverage").json()["groups"][0]["grid"]["planned_cells"] == 4
    assert client.post("/api/projects/" + project, json={**PROJECT, "expected_revision": 1}).status_code == 200
    repeat = client.post(base + "/crossed", json=spec, headers=headers)
    assert repeat.status_code == 202 and repeat.json() == submit.json()
    assert client.post(base + "/crossed", json=spec).status_code == 409
    # Even if every row for the reference force disappears, its two planned cells
    # and the saved design remain available. No surviving cell becomes reference.
    with app.state.store.connection(True) as db:
        db.execute("DELETE FROM project_runs WHERE suite_id=? AND json_extract(inputs,'$.tip_force_n')=5", (suite,))
    detail = client.get(base + "/" + suite).json()
    assert len(detail["runs"]) == 2 and detail["total"] == 4 and not any(row["reference"] for row in detail["runs"])
    assert detail["crossed_design"]["reference"] == {"tip_force_n": 5, "face_pressure_pa": 0}
    missing = client.get(base + "/" + suite + "/coverage").json()["groups"][0]
    assert missing["grid"]["possible_cells"] == missing["grid"]["planned_cells"] == 4
    assert missing["counts"]["blocked"] == 2
    with app.state.store.connection(True) as db:
        db.execute("DELETE FROM project_runs WHERE suite_id=?", (suite,))
    assert client.get(base + "/" + suite + "/coverage").json()["groups"][0]["counts"]["blocked"] == 4
    history = client.get("/api/project-campaigns").json()["items"]
    assert len(history) == 1 and history[0]["total"] == 4 and history[0]["status"] == "partial"


def test_cross_two_named_robot_targets_preserves_other_targets_and_rejects_unsafe_grids():
    snapshot = {"analysis_type": "robot_behavior", "revision": 1, "parameters": []}
    body = {"expected_revision": 1, "label": "Paired targets", "adapter": "robot_motion",
            "inputs": {"targets": {"joint.a": 0.2, "b": 0, "c": 0.1}},
            "axes": [{"field": "targets.joint.a", "values": [0, 0.2]}, {"field": "targets.b", "values": [0, 0.1]}]}
    def plan(axes):
        return crossed_tests(CrossedCampaign.model_validate({**body, "axes": axes}), snapshot)
    assert [t.inputs["targets"]["c"] for t in plan(body["axes"])] == [0.1] * 4
    assert body["inputs"]["targets"] == {"joint.a": 0.2, "b": 0, "c": 0.1}
    a, b = body["axes"]
    for axes in ([a, a], [a, {**b, "values": [0, 0]}], [a, {**b, "values": [1, 2]}],
                 [a, {**b, "field": "tolerance"}], [a, {**b, "values": [False, 1]}],
                 [{**a, "values": [0, 0.2, 0.4, 0.6, 1]}, {**b, "values": [0, 1, 2, 3]}]):
        with pytest.raises(ValueError):
            plan(axes)


def test_ambient_temperature_and_internal_heating_execute_as_a_complete_cross(tmp_path):
    inputs = {**ROD, "left_temperature_k": 300, "right_ambient_temperature_k": 300,
              "right_film_coefficient_w_m2k": 500, "heat_generation_w_m3": 0, "max_temperature_k": 315}
    del inputs["right_temperature_k"]
    with TestClient(create_app(tmp_path)) as client:
        warmup = {"id": "warmup", "name": "Warm up", "question": "What touches the rod before heating?", "conditions": []}
        project = {**PROJECT, "analysis_type": "thermal", "task_phases": [warmup],
            "operating_factors": [{"name": "Ambient", "field": "right_ambient_temperature_k",
                                  "unit": "K", "required_values": [300, 320, 340]}]}
        owner = client.post("/api/projects", json=project).json()["id"]
        path = "/api/project-campaigns/" + owner
        submit = client.post(path + "/crossed", json={"adapter": "thermal_rod", "expected_revision": 1,
            "label": "Ambient and generated heat", "inputs": inputs,
            "axes": [{"field": "right_ambient_temperature_k", "values": [300, 340]},
                     {"field": "heat_generation_w_m3", "values": [0, 600000]}]})
        assert submit.status_code == 202, submit.text
        url = path + "/" + submit.json()["suite_id"] + "/coverage"
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            group, = client.get(url).json()["groups"]
            if group["counts"]["pending"] == 0:
                break
            time.sleep(0.1)
        assert group["grid"] == {"planned_cells": 4, "observed_cells": 4, "possible_cells": 4, "unobserved_cells": 0}
        assert group["counts"]["passed"] > 0 and group["counts"]["failed"] > 0 and group["matched_change"]
        assert group["declared_factors"][0]["untested_values"] == [320]
        # Updating the engineer's operating review after the grid ran must keep both
        # its original unanswered phase and the open physical test visible.
        condition = {"id": "vent", "answer": "A loading door changes the air speed",
                     "status": "physically_testable", "reason": "Local airflow is unknown",
                     "next_step": "Measure airspeed at the end face during a door cycle"}
        update = client.post("/api/projects/" + owner, json={**project, "expected_revision": 1,
            "task_phases": [{**warmup, "conditions": [condition]}]})
        assert update.status_code == 200, update.text
        coverage = client.get(url).json()
        assert coverage["groups"] == [group]
        review = coverage["phase_review"]
        assert review["current_revision"] == 2 and review["campaign_revision"] == 1
        assert review["campaign_phases"] == [warmup]
        current, = review["current_phases"][0]["conditions"]
        assert all(current[key] == value for key, value in condition.items())
        assert review["submitted_condition"] is None
