import csv
import hashlib
import io
import json

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.hardware_trials import COLUMNS, acceptance_metrics, evaluate_trials


def as_csv(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def test_physical_trial_file_matches_original_run_after_upload(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    spec = {"name": "Beam test", "entry_stage": "prototype", "analysis_type": "structural",
            "goal": "Check an end-loaded beam", "success_criteria": "Deflection within limit"}
    project = client.post("/api/projects", json=spec).json()["id"]
    project_path = f"/api/projects/{project}"
    run = client.post(project_path + "/analysis", json={"expected_revision": 1, "label": "Beam",
                      "adapter": "structural_beam", "inputs": {"max_displacement_m": 0.003}}).json()["id"]
    path = project_path + f"/analysis/{run}/hardware-trials"
    assert client.get(path).status_code == 409
    result = {"inputs": {"tip_force_n": 5}, "acceptance_checks": [{"quantity": "continuous_max_abs_displacement_m",
              "measured": 0.0025, "maximum": 0.003}], "numerical_diagnostics": {"passed": True}}
    digest = "a" * 64
    with app.state.store.connection(True) as db:
        db.execute("UPDATE project_runs SET status='completed',result=?,evidence_hash=? WHERE id=?",
                   (json.dumps(result), digest, run))
    assert client.get(path).json()["assets"] == []
    template = client.get(path + "/template.csv")
    assert template.status_code == 200
    row = next(csv.DictReader(io.StringIO(template.text)))
    assert row["run_id"] == run and row["evidence_hash"] == digest and row["measured_value"] == ""
    common = {**row, "unit": "mm", "prototype_id": "fixture-A", "condition_record": "Tip load",
              "trial_settings_json": '{"tip_force_n":5}'}
    observations = [{**common, "trial_id": str(i), "measured_value": value, "absolute_uncertainty": u}
                    for i, (value, u) in enumerate([(2.7, .1), (3.5, .2), (3.0, .2), (3.0, 0)])]
    observations.append({**observations[0], "trial_id": "off-point", "trial_settings_json": '{"tip_force_n":7}'})
    observations.append({**observations[3], "trial_id": "just over", "measured_value": "3.0000000000000001"})
    data = as_csv(observations).encode()
    upload = client.post(project_path + "/assets?filename=trial.csv&kind=measurements", content=data)
    assert upload.status_code == 201 and upload.json()["revision"] == 2
    asset = upload.json()["assets"][0]["id"]
    response = client.get(path + "/" + asset)
    assert response.status_code == 200
    report = response.json()
    assert report["project_revision"] == 1 and report["evidence_hash"] == digest
    assert report["asset_sha256"] == hashlib.sha256(data).hexdigest()
    assert [r["agreement"] for r in report["rows"]] == ["agrees", "disagrees", "indeterminate", "agrees", "unmatched settings", "disagrees"]
    assert report["rows"][4]["differing_settings"] == ["tip_force_n"]
    assert report["rows"][1]["residual"] == pytest.approx(.001)
    assert client.get(path).json()["assets"][0]["id"] == asset
    other = client.post("/api/projects", json=spec).json()["id"]
    assert client.get(path.replace(project, other) + "/" + asset).status_code == 404


@pytest.mark.parametrize("change", [{"evidence_hash": "another"}, {"run_id": "foreign"}, {"unit": "kg"},
                                    {"metric": "unknown"}, {"absolute_uncertainty": "-1"},
                                    {"absolute_uncertainty": ""}, {"measured_value": "nan"},
                                    {"measured_value": "inf"}, {"condition_record": ""}])
def test_incompatible_or_unattributed_observations_are_rejected(change):
    run = {"id": "run", "evidence_hash": "evidence", "adapter": "packaging_lift",
           "result": {"summary": {"max_hold_error_m": .012, "error_limit_m": .01}}}
    row = {"run_id": "run", "evidence_hash": "evidence", "metric": "max_hold_error_m", "unit": "m",
           "simulated_settings_json": "{}", "trial_settings_json": "{}",
           "prototype_id": "A", "trial_id": "P1", "condition_record": "0.5 kg, 2 N",
           "measured_value": .009, "absolute_uncertainty": .001}
    with pytest.raises(ValueError):
        evaluate_trials(io.StringIO(as_csv([{**row, **change}])), run, acceptance_metrics(run))
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_trials(io.StringIO(as_csv([row, row])), run, acceptance_metrics(run))


def test_operating_requirements_persist_on_revision_and_old_client_saves(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    base = {"name": "Mount", "entry_stage": "prototype", "analysis_type": "structural",
            "goal": "Hold sensor", "success_criteria": "Stay level"}
    factor = {"name": "Humidity", "field": "", "unit": "%", "conditions": "Wet installation",
              "required_values": [40, 90]}
    p = client.post("/api/projects", json={**base, "operating_factors": [factor]}).json()
    path = "/api/projects/" + p["id"]
    assert client.post(path, json={**base, "expected_revision": 1}).json()["operating_factors"] == [factor]
    assert client.post(path, json={**base, "expected_revision": 2, "operating_factors": []}).json()["operating_factors"] == []
    assert client.get(path + "/revisions/1").json()["operating_factors"] == [factor]
    assert client.post("/api/projects", json={**base, "operating_factors": [factor, factor]}).status_code == 422


def test_robot_speed_uses_recorded_solver_tolerance_and_joint_units():
    run = {"adapter": "robot_motion", "result": {"criteria": {"joint_target_tolerance": 0.01},
           "model": {"joints": [{"name": "slide", "unit": "m", "velocity_limit": 0.5}]},
           "metrics": {"final_absolute_joint_error": {"slide": 0.011}, "peak_joint_speed": {"slide": 0.5000000001}}}}
    metrics = acceptance_metrics(run)
    assert metrics["peak_joint_speed.slide"]["simulation_verdict"] == "pass"
    assert metrics["peak_joint_speed.slide"]["maximum"] == 0.5
    assert metrics["final_absolute_joint_error.slide"]["simulation_verdict"] == "fail"


def test_one_physical_trial_cannot_change_configuration_between_metrics():
    run = {"id": "r", "evidence_hash": "hash", "adapter": "packaging_lift", "result": {
        "summary": {"head_force_n": 2, "max_hold_error_m": .012, "arrival_error_m": .003, "error_limit_m": .01}}}
    row = {"run_id": "r", "evidence_hash": "hash", "prototype_id": "test", "trial_id": "trial",
           "condition_record": "fixture", "simulated_settings_json": '{"head_force_n":2}',
           "trial_settings_json": '{"head_force_n":2}', "unit": "m", "metric": "max_hold_error_m",
           "measured_value": .011, "absolute_uncertainty": .001}
    other = {**row, "trial_settings_json": '{"head_force_n":1}', "metric": "arrival_error_m"}
    with pytest.raises(ValueError, match="settings changed"):
        evaluate_trials(io.StringIO(as_csv([row, other])), run, acceptance_metrics(run))


@pytest.mark.parametrize("unit,value,uncertainty", [("mm", "9.8", "0.2"), ("cm", ".98", ".02"),
                                                   ("m", ".0098", ".0002")])
def test_inclusive_limit_and_uncertainty_are_invariant_to_unit(unit, value, uncertainty):
    run = {"id": "run", "evidence_hash": "hash", "adapter": "packaging_lift",
           "result": {"summary": {"max_hold_error_m": .009, "error_limit_m": .01, "head_force_n": 2}}}
    row = {"run_id": "run", "evidence_hash": "hash", "prototype_id": "test", "trial_id": "test-1",
           "condition_record": "test fixture", "simulated_settings_json": '{"head_force_n":2}',
           "trial_settings_json": '{"head_force_n":2}', "metric": "max_hold_error_m", "unit": unit,
           "measured_value": value, "absolute_uncertainty": uncertainty}
    result, = evaluate_trials(io.StringIO(as_csv([row])), run, acceptance_metrics(run))
    assert (result["physical_verdict"], result["agreement"]) == ("pass", "agrees")
