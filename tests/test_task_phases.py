import time

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.project_solver import BEAM, ROD
from failureforge.projects import ProjectSpec
from failureforge.task_phases import ConditionTest


def lift(**changes):
    return {"name": "Tray handling", "analysis_type": "robot_behavior", "entry_stage": "prototype",
            "goal": "Raise and release the tray", "success_criteria": "Keep the hold position",
            "robot_source": "supported", "robot_template": "packaging_lift_v1", **changes}


def timing_test(**changes):
    return {"adapter": "packaging_lift_timed_v2", "field": "head_onset_ms",
            "reference_inputs": {"head_onset_ms": 1000, "head_duration_ms": 400, "payload_kg": 0.5, "head_force_n": 2},
            "changed_value": 750, **changes}


def phase_review():
    return [{"id": "rise", "name": "Travel", "question": "What changes the load during travel?",
             "conditions": [
                 {"id": "guide", "answer": "Wash water wets the guide", "status": "physically_testable",
                  "reason": "The fixture has no wet-contact friction law", "next_step": "Measure breakaway force dry and wet"},
                 {"id": "timing", "answer": "Head engagement varies", "status": "modeled", "test": timing_test(),
                  "reason": "The timing input controls the start of the force pulse", "next_step": "Compare early engagement with nominal"},
                 {"id": "offset", "answer": "The tray can sit off center", "status": "outside_model",
                  "reason": "The one-axis model omits tray moment", "next_step": "Measure the offset and guide reactions"}]}]


def test_review_survives_legacy_edits_and_runs_a_real_isolated_condition_pair(tmp_path):
    app = create_app(tmp_path)
    phases = phase_review()
    with TestClient(app) as client:
        project = client.post("/api/projects", json=lift()).json()
        url = "/api/projects/" + project["id"]
        record = client.post(url, json=lift(expected_revision=1, task_phases=phases))
        assert record.status_code == 200, record.text
        findings = record.json()["task_phases"]
        base = url + "/task-phases/rise/conditions/"
        headers = {"Idempotency-Key": "recorded-phase-run"}
        assert client.post(base + "guide/run", json={"expected_revision": 2}, headers=headers).status_code == 422
        launch = client.post(base + "timing/run", json={"expected_revision": 2}, headers=headers)
        assert launch.status_code == 202, launch.text
        suite = launch.json()["suite_id"]
        limit = time.monotonic() + 35
        while time.monotonic() < limit:
            rows = client.get(url + "/analysis-suite/" + suite).json()["runs"]
            if not any(r["status"] in ("queued", "running") for r in rows):
                break
            time.sleep(.08)
        before, after = rows
        assert before["status"] == after["status"] == "completed", [r["error"] for r in rows]
        assert before["inputs"]["head_onset_ms"] == 1000
        assert after["inputs"] == {**before["inputs"], "head_onset_ms": 750}
        assert before["snapshot"]["task_phases"] == after["snapshot"]["task_phases"] == findings
        assert client.get(url + "/revisions/2").json()["task_phases"] == findings
        assert client.get(url + "/export").json()["project"]["task_phases"] == findings
        with app.state.store.connection() as db:
            row = db.execute("SELECT * FROM project_phase_tests WHERE suite_id=?", (suite,)).fetchone()
            assert (row["phase_id"], row["condition_id"], row["project_revision"]) == ("rise", "timing", 2)
        updated = client.post(url, json=lift(notes="Changed from an older client", expected_revision=2))
        assert updated.json()["task_phases"] == findings
        repeat = client.post(base + "timing/run", json={"expected_revision": 2}, headers=headers)
        assert repeat.json()["suite_id"] == suite
        assert client.post(base + "timing/run", json={"expected_revision": 2},
                           headers={"Idempotency-Key": "different-request"}).status_code == 409
        assert client.post(url, json=lift(expected_revision=3, robot_source="custom", robot_template=None)).status_code == 422
        removed = client.post(url, json=lift(expected_revision=3, task_phases=[]))
        assert removed.json()["task_phases"] == []
        assert client.get(url + "/revisions/2").json()["task_phases"] == findings
        assert client.post(base + "timing/run", json={"expected_revision": 4}, headers={"Idempotency-Key": "removed-test"}).status_code == 404


@pytest.mark.parametrize("mutate", [
    lambda p: p.extend(p),
    lambda p: p[0]["conditions"].append(p[0]["conditions"][0]),
    lambda p: p[0]["conditions"][0].update(status="modeled"),
    lambda p: p[0]["conditions"][1].update(status="outside_model"),
    lambda p: p[0]["conditions"][1]["test"].update(field="wet_friction"),
    lambda p: p[0]["conditions"][1]["test"].update(changed_value=1000),
    lambda p: p[0]["conditions"][1]["test"].update(changed_value=1750),
    lambda p: p[0]["conditions"][1]["test"]["reference_inputs"].update(head_force_n=0),
    lambda p: p[0]["conditions"][2].update(reason=" "),
])
def test_rejects_ambiguous_or_unexecutable_dispositions(mutate):
    phases = phase_review()
    mutate(phases)
    with pytest.raises(ValueError):
        ProjectSpec.model_validate(lift(task_phases=phases))


@pytest.mark.parametrize("adapter,base,field,value", [
    ("structural_beam", BEAM, "tip_force_n", 8),
    ("thermal_rod", ROD, "heat_generation_w_m3", 15000),
    ("robot_motion", {"targets": {"joint1": 0.1}}, "targets.joint1", 0.2),
])
def test_pair_uses_solver_controls_without_mutating_the_input(adapter, base, field, value):
    test = ConditionTest(adapter=adapter, reference_inputs=base, field=field, changed_value=value)
    before, after = test.pair()
    if adapter == "robot_motion":
        assert before["targets"]["joint1"] == 0.1 and after["targets"]["joint1"] == value
    else:
        assert after == {**before, field: value} and before[field] != value
