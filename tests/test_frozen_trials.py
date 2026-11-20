import json

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.contracts import config_hash
from failureforge.engineering import run_engineering
from failureforge.frozen_trials import PhysicalReading, compare_reading, observables, operating_settings, setting_units
from failureforge.project_solver import BEAM, ROD


@pytest.fixture
def workbench(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Cantilever", "entry_stage": "prototype",
        "analysis_type": "structural", "goal": "Characterize the mounted beam", "success_criteria": "Predict stiffness"}).json()["id"]
    path = "/api/projects/" + project
    job = client.post(path + "/analysis", json={"expected_revision": 1, "label": "Linear probe",
                                                "adapter": "structural_beam", "inputs": BEAM}).json()
    run = job["id"]
    base = f"{path}/analysis/{run}/hardware-trials/predictions"
    assert client.get(base).status_code == 409
    record = client.get(f"{path}/analysis/{run}").json()
    result = run_engineering(BEAM)
    parts = {key: record[key] for key in ("snapshot", "inputs", "adapter", "runtime")}
    digest = config_hash({**parts, "result": result})
    with app.state.store.connection(True) as db:
        db.execute("UPDATE project_runs SET status='completed',result=?,evidence_hash=? WHERE id=?",
                   (json.dumps(result), digest, run))
    return client, base, app


FREEZE = {"observable_id": "tip_stiffness_n_per_m", "prototype_id": "fixture #2",
          "setup": "Rectangular cantilever with a transverse end load. Nominal section from the drawing."}
READING = {"prototype_id": "fixture #2", "trial_id": "bench-2", "source": "Independent laboratory log, row 2",
           "condition_record": "Single end-loaded cantilever. Slope of static force versus displacement.",
           "source_kind": "published", "independent": True, "fixture_matches": True, "actual_settings": {},
           "station_reference": "free_end", "value": 43.75, "unit": "N/mm",
           "uncertainty": 0.20, "uncertainty_basis": "Reported expanded uncertainty, coverage factor 2."}


def submit(client, path, body, key="a-valid-idempotency-key"):
    return client.post(path, json=body, headers={"Idempotency-Key": key})


def test_freeze_without_limit_then_record_independent_interval(workbench):
    client, base, app = workbench
    choices = client.get(base).json()["observables"]
    stiffness = next(item for item in choices if item["id"] == FREEZE["observable_id"])
    assert stiffness["prediction"] == pytest.approx(43_750)
    frozen = submit(client, base, FREEZE)
    assert frozen.status_code == 201
    prediction = frozen.json()
    assert prediction["observable"] == stiffness and prediction["settings"] == {}
    assert prediction["hash"] == config_hash({k: v for k, v in prediction.items() if k != "hash"})
    assert submit(client, base, FREEZE).json() == prediction
    assert submit(client, base, {**FREEZE, "setup": "changed input"}).status_code == 409
    path = base + "/" + prediction["id"]
    assert client.get(path).json() == {"prediction": prediction, "measurements": []}
    result = submit(client, path + "/measurements", READING)
    assert result.status_code == 201, result.text
    record = result.json()
    assert record["conclusion"] == "agrees" and record["interval"] == [43550, 43950]
    assert record["source_unit"] == "N/mm" and record["unit"] == "N/m"
    assert record["recorded_at"] >= prediction["frozen_at"] and record["prediction_hash"] == prediction["hash"]
    assert submit(client, path + "/measurements", READING).json() == record
    assert submit(client, path + "/measurements", READING, "different-idempotency-key").status_code == 409
    assert client.get(path).json() == {"prediction": prediction, "measurements": [record]}
    assert client.post(path, json=FREEZE).status_code == 405
    assert client.delete(path).status_code == 405
    other_project = client.post("/api/projects", json={"name": "Other beam", "entry_stage": "prototype",
        "analysis_type": "structural", "goal": "Trial", "success_criteria": "Measure deflection"}).json()["id"]
    assert client.get(path.replace(prediction["project_id"], other_project)).status_code == 404
    with app.state.store.connection(True) as db:
        db.execute("UPDATE frozen_predictions SET record=? WHERE id=?",
                   (json.dumps({**prediction, "setup": "modified after freeze"}), prediction["id"]))
    assert client.get(path).status_code == 409


@pytest.mark.parametrize(("change", "verdict"), [
    ({"value": 46}, "disagrees"), ({"uncertainty": None, "uncertainty_basis": "Not reported"}, "indeterminate"),
    ({"actual_settings": {"head_force_n": 32}}, "indeterminate"), ({"prototype_id": "different"}, "indeterminate"),
    ({"station_reference": "unknown"}, "indeterminate"), ({"independent": False}, "indeterminate"),
    ({"fixture_matches": False}, "indeterminate"), ({"unit": "kg"}, None), ({"uncertainty": 0}, None),
    ({"source_kind": "new_trial", "measured_at": "2020-01-01T00:00:00Z"}, None),
    ({"source_kind": "new_trial"}, None), ({"asset_id": "nonexistent"}, None),
])
def test_differing_or_unknown_physical_evidence(workbench, change, verdict):
    client, base, _ = workbench
    prediction = submit(client, base, FREEZE).json()
    result = submit(client, base + "/" + prediction["id"] + "/measurements", {**READING, **change})
    if verdict is None:
        assert result.status_code == 422
    else:
        assert result.status_code == 201 and result.json()["conclusion"] == verdict


def test_station_identity_and_signed_reading(workbench):
    client, base, _ = workbench
    frozen = submit(client, base, {**FREEZE, "observable_id": "displacement_m@16"}).json()
    assert frozen["observable"]["station_m"] == pytest.approx(.1)
    path = base + "/" + frozen["id"] + "/measurements"
    reading = {**READING, "actual_settings": frozen["settings"], "station_reference": "from_origin",
               "station_m": .1, "value": -1, "unit": "mm", "uncertainty": .2}
    assert submit(client, path, reading).json()["conclusion"] == "disagrees"
    off_station = submit(client, path, {**reading, "trial_id": "bench-3", "station_m": .2}, "a-second-key").json()
    assert off_station["conclusion"] == "indeterminate" and any("station" in r for r in off_station["reasons"])


@pytest.mark.parametrize("change", [{"tip_force_n": 0}, {"face_pressure_pa": 1}, {"distributed_load_n_per_m": .5},
                                    {"span_loads": [{"start_fraction": .5, "end_fraction": .5, "force_n": .25}]}])
def test_stiffness_requires_an_isolated_linear_tip_load(change):
    result = run_engineering({**BEAM, **change})
    assert FREEZE["observable_id"] not in {item["id"] for item in observables({"adapter": "structural_beam", "result": result})}


def test_thermal_station_available_without_a_threshold():
    result = run_engineering(ROD)
    choices = observables({"adapter": "thermal_rod", "result": result})
    assert choices and all(choice["unit"] == "K" and choice["station_reference"] == "from_origin" for choice in choices)
    cold = choices[0]
    frozen = {"observable": cold, "prototype_id": READING["prototype_id"], "settings": {"ambient_k": 295}}
    reading = PhysicalReading(**{**READING, "unit": "°C", "value": 20.0, "uncertainty": .75,
                                 "actual_settings": frozen["settings"], "station_reference": "from_origin", "station_m": 0})
    result = compare_reading(frozen, reading)
    assert result["measured"] == 293.15 and result["interval"] == [292.4, 293.9] and result["conclusion"] == "agrees"


def test_stationary_lift_and_robot_trial_conditions_include_the_observation_window():
    lift = {"adapter": "packaging_lift", "result": {"fixture": {"arrival_deadline_s": 1, "end_time_s": 2, "target_m": .15},
            "summary": {"max_hold_error_m": .014, "error_limit_m": .010, "payload_kg": .5, "head_force_n": 2}}}
    settings = operating_settings(lift, observables(lift)[0])
    assert settings == {"head_force_n": 2, "payload_kg": .5, "target_m": .15, "arrival_deadline_s": 1, "end_time_s": 2}
    robot = {"adapter": "robot_motion", "inputs": {"targets": {"j1": .3}}, "result": {
        "trajectory": {"time_s": [0, 2], "joint_positions": {"j1": [-.2, .29]}},
        "model": {"joints": [{"name": "j1", "unit": "rad"}]}, "criteria": {"joint_target_tolerance": .02},
        "metrics": {"final_absolute_joint_error": {"j1": .01}}}}
    settings = operating_settings(robot, observables(robot)[0])
    assert settings == {"initial.j1": -.2, "duration_s": 2, "targets.j1": .3}
    assert setting_units(robot, settings) == {"initial.j1": "rad", "duration_s": "s", "targets.j1": "rad"}
