import json

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app


@pytest.fixture
def history(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Probe", "entry_stage": "concept", "analysis_type": "thermal",
                          "goal": "Test temperatures", "success_criteria": "Peak below 315 K"}).json()["id"]
    base = "/api/projects/" + project

    def record(value, passed, *, inputs=None, result=None, **overrides):
        case = {"adapter": "thermal_rod", "label": f"Test {value}",
                "inputs": {"heat_generation_w_m3": value, "max_temperature_k": 315, **(inputs or {})}}
        run = client.post(base + "/analysis", json={"expected_revision": 1, **case}).json()
        columns = {"status": "completed", "evidence_hash": "test-hash", "runtime": '{"solver":"1"}',
                   "result": json.dumps({"passed": passed, **(result or {})}), **overrides}
        with app.state.store.connection(True) as db:
            db.execute("UPDATE project_runs SET " + ",".join(key + "=?" for key in columns) + " WHERE id=?",
                       (*columns.values(), run["id"]))
        return run["id"]

    return record, lambda: client.get(base + "/replay-pair").json()["pair"]


def test_closest_single_factor_pair_across_independent_runs(history):
    record, pair = history
    record(0, True)
    failed = record(3, False)
    passed = record(2, True)
    selected = pair()
    assert (selected["left"]["id"], selected["right"]["id"]) == (passed, failed)
    assert selected["field"] == "heat_generation_w_m3"
    assert selected["suite_id"] is None


def test_multiple_inputs_acceptance_runtime_and_model_validity_block_attribution(history):
    record, pair = history
    record(10, True)
    record(10, False, inputs={"max_temperature_k": 300})
    record(12, False, inputs={"elements": 30})
    record(20, False, runtime='{"solver":"2"}')
    record(25, False, project_revision=2)
    record(30, False, result={"numerical_diagnostics": {"passed": False}})
    record(40, False, result={"dynamics": {"reference_qualification": [{"passed": False}]}})
    record(45, False, evidence_hash=None)
    record(50, False, result={"model": {"reference_id": "two_finger_hand_v1"}})
    record(60, None)
    assert pair() is None


def test_disagreeing_repeats_are_excluded(history):
    record, pair = history
    record(0, True)
    record(5, False)
    record(5, True)
    assert pair() is None
