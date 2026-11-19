import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.cli import parser
from failureforge.project_bindings import resolve_bindings
from failureforge.project_ci import execute
from failureforge.project_runs import ProjectTest


BASE = {"name": "Cantilever specimen", "entry_stage": "prototype", "analysis_type": "structural",
        "goal": "Track deflection", "success_criteria": "100 N within the declared tip limit"}
MATERIAL = {"name": "young_modulus_pa", "source": "estimated", "unit": "GPa", "value": "200",
            "range_min": 10., "range_max": 300., "evidence": "Initial estimate"}
SHAPE = {"length_m": 1., "width_m": .03, "height_m": .04, "tip_force_n": 100., "max_displacement_m": .002}
CHECK = {"label": "100 N check", "adapter": "structural_beam", "inputs": SHAPE,
         "bindings": {"young_modulus_pa": "young_modulus_pa"}}


class Transport:
    def __init__(self, client):
        self.client = client

    def request(self, method, path, *, timeout, data=None, key=None):
        response = self.client.request(method, path, json=data, headers={"Idempotency-Key": key} if key else {})
        assert response.is_success, response.text
        return response.json()


def material_calibration():
    def reading(run_id, load):
        inertia = .03 * .04**3 / 12
        return {"run_id": run_id, "tip_force_n": load, "tip_displacement_m": load/(3*50e9*inertia)}

    return {"label": "analytic calibration fixture", "adapter": "calibration",
            "inputs": {"model": {"kind": "structural_beam", **SHAPE, "young_modulus_pa": 200e9},
                       "parameter_bounds": [1e9, 300e9], "validation_tolerance": 1e-7,
                       "fit": [reading("fixture A", 10)], "validation": [reading("fixture B", 30)]}}


def test_promoted_measurement_drives_frozen_suite_on_new_revision(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project = client.post("/api/projects", json={**BASE, "parameters": [MATERIAL]}).json()["id"]
        path = f"/api/projects/{project}"
        catalog = client.get(path+"/analysis").json()["adapters"]
        beam = next(item for item in catalog if item["id"] == "structural_beam")
        assert beam["binding_units"]["young_modulus_pa"] == "Pa"
        assert "GPa" in beam["binding_accepted_units"]["young_modulus_pa"]
        def ci(*opts):
            args = parser().parse_args(["project-ci", project, "--poll-interval", ".05", *opts])
            return execute(args, api=Transport(client))

        fixed = {"label": "fixed reference", "adapter": "structural_beam", "inputs": {**SHAPE, "young_modulus_pa": 200e9}}
        spec = tmp_path/"tests.json"
        spec.write_text(json.dumps({"tests": [CHECK, fixed]}))
        first, code = ci("--spec", str(spec), "--idempotency-key", "bound-suite-check")
        assert code == 0
        original = client.get(path+"/analysis/"+first["runs"][0]["id"]).json()
        assert original["inputs"]["young_modulus_pa"] == 200e9
        assert original["definition"] == CHECK
        evidence = original["binding_evidence"]["young_modulus_pa"]
        assert (evidence["source_unit"], evidence["resolved_unit"], evidence["source"]) == ("GPa", "Pa", "estimated")
        fixed_id = first["runs"][1]["id"]
        changed_definition = client.get(f"{path}/analysis/{original['id']}/compare/{fixed_id}").json()
        assert changed_definition["outcome"] == "not_comparable"
        assert changed_definition["changed_inputs"] == {}
        assert changed_definition["changed_bindings"]["young_modulus_pa"]["candidate"] is None

        recent = client.post(path+"/analysis", json={**CHECK, "label": "repeated load check",
                             "bindings": {"young_modulus_pa": "YOUNG_MODULUS_PA"}, "expected_revision": 1}).json()
        spec.write_text(json.dumps(material_calibration()))
        cal, code = ci("--spec", str(spec))
        assert code == 0
        promoted = client.post(path+"/analysis/"+cal["runs"][0]["id"]+"/promote", json={"expected_revision": 1})
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["revision"] == 2
        rechecks = promoted.json()["rechecks"]
        assert rechecks["previous_run_ids"] == [recent["id"]]
        assert not rechecks["more_available"] and len(rechecks["run_ids"]) == 1
        automatic = client.get(path+"/analysis/"+rechecks["run_ids"][0]).json()
        assert (automatic["recheck_of"], automatic["calibration_run_id"]) == (recent["id"], cal["runs"][0]["id"])
        assert automatic["suite_id"] == rechecks["suite_id"] and automatic["project_revision"] == 2
        assert automatic["snapshot"]["parameters"] == promoted.json()["parameters"]
        assert automatic["inputs"]["young_modulus_pa"] == pytest.approx(50e9)
        assert client.post(path+"/analysis/"+cal["runs"][0]["id"]+"/promote", json={"expected_revision": 1}).status_code == 409
        assert len([item for item in client.get(path+"/analysis").json()["runs"] if item["project_revision"] == 2]) == 1
        second, code = ci("--rerun-suite", first["suite_id"])
        assert code == 1
        assert [c["outcome"] for c in second["comparisons"]] == ["new_failure", "unchanged_pass"]
        candidate = client.get(path+"/analysis/"+second["runs"][0]["id"]).json()
        assert candidate["definition"] == original["definition"]
        assert candidate["inputs"]["young_modulus_pa"] == pytest.approx(50e9)
        assert candidate["binding_evidence"]["young_modulus_pa"]["source"] == "calibrated"
        assert cal["runs"][0]["evidence_hash"] in candidate["binding_evidence"]["young_modulus_pa"]["evidence"]
        assert candidate["evidence_hash"] != original["evidence_hash"]
        old = client.get(path+"/analysis/"+original["id"]).json()
        assert old["binding_evidence"] == original["binding_evidence"]
        report = second["comparisons"][0]
        assert report["changed_inputs"]["young_modulus_pa"]["baseline"] == 200e9
        assert report["changed_bindings"] == {}
        prior = client.post(path+"/analysis-suite", json={"expected_revision": 1, "tests": [CHECK, fixed]},
                            headers={"Idempotency-Key": "bound-suite-check"})
        assert prior.status_code == 202 and prior.json()["suite_id"] == first["suite_id"]


def completed_calibration(client, project, tmp_path):
    spec = tmp_path/"fixture.json"
    spec.write_text(json.dumps(material_calibration()))
    args = parser().parse_args(["project-ci", project, "--poll-interval", ".05", "--spec", str(spec)])
    report, code = execute(args, api=Transport(client))
    assert code == 0
    return report["runs"][0]["id"]


def test_promotion_rechecks_most_recent_bounded_definitions_on_prior_revision(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        data = {**BASE, "parameters": [MATERIAL]}
        project = client.post("/api/projects", json=data).json()["id"]
        path = f"/api/projects/{project}"
        old = client.post(path+"/analysis", json={**CHECK, "expected_revision": 1}).json()["id"]
        assert client.post(path, json={**data, "expected_revision": 1}).status_code == 200
        calibration = completed_calibration(client, project, tmp_path)
        tests = [{**CHECK, "label": f"Load {force}", "inputs": {**SHAPE, "tip_force_n": force}} for force in range(1, 18)]
        first = client.post(path+"/analysis-suite", json={"tests": tests[:16], "expected_revision": 2}).json()["runs"]
        newest = client.post(path+"/analysis", json={**tests[-1], "expected_revision": 2}).json()["id"]
        update = client.post(path+"/analysis/"+calibration+"/promote", json={"expected_revision": 2}).json()
        assert update["revision"] == 3
        receipt = update["rechecks"]
        assert receipt["more_available"] and len(set(receipt["run_ids"])) == 16
        assert old not in receipt["previous_run_ids"]
        assert set(receipt["previous_run_ids"]) == {newest, *(item["id"] for item in first[1:])}


def test_promotion_and_rechecks_roll_back_if_new_value_cannot_resolve(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        # A prior geometry check used a length-valued project parameter of the same name.
        previous = {**MATERIAL, "unit": "m", "value": "1", "range_min": None, "range_max": None}
        project = client.post("/api/projects", json={**BASE, "parameters": [previous]}).json()["id"]
        path = f"/api/projects/{project}"
        calibration = completed_calibration(client, project, tmp_path)
        inputs = {**SHAPE, "young_modulus_pa": 200e9}
        del inputs["length_m"]
        check = {**CHECK, "inputs": inputs, "bindings": {"length_m": MATERIAL["name"]}, "expected_revision": 1}
        assert client.post(path+"/analysis", json=check).status_code == 202
        conflict = client.post(path+"/analysis/"+calibration+"/promote", json={"expected_revision": 1})
        assert conflict.status_code == 422 and "compatible" in conflict.text
        unchanged = client.get(path).json()
        assert unchanged["revision"] == 1 and unchanged["parameters"] == [previous]
        assert client.get(path+"/revisions/2").status_code == 404
        assert all(item["project_revision"] == 1 for item in client.get(path+"/analysis").json()["runs"])


def test_concurrent_promotion_without_dependent_checks_saves_one_revision(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project = client.post("/api/projects", json=BASE).json()["id"]
        path = f"/api/projects/{project}"
        calibration = completed_calibration(client, project, tmp_path)
        url = path+"/analysis/"+calibration+"/promote"
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(client.post, url, json={"expected_revision": 1}) for _ in range(2)]
            responses = [request.result() for request in requests]
        assert sorted(r.status_code for r in responses) == [200, 409]
        saved = next(r.json() for r in responses if r.is_success)
        assert saved["revision"] == 2
        assert saved["rechecks"] == {"suite_id": None, "run_ids": [], "previous_run_ids": [], "more_available": False}
        assert len(client.get(path+"/analysis").json()["runs"]) == 1


@pytest.mark.parametrize(("updates", "parameter", "expected"), [
    ({"bindings": {"unknown": "young_modulus_pa"}}, MATERIAL, "bindable scalar"),
    ({"bindings": {"young_modulus_pa": "other"}}, MATERIAL, "missing"),
    ({"inputs": {**SHAPE, "young_modulus_pa": 9}}, MATERIAL, "literal input"),
    ({}, {**MATERIAL, "unit": "mm"}, "compatible"),
    ({}, {**MATERIAL, "value": "200 ± 1"}, "finite number"),
    ({}, {**MATERIAL, "value": "1e1000"}, "overflows"),
    ({}, {**MATERIAL, "value": "900"}, "declared range"),
    ({}, {**MATERIAL, "value": "0.001", "unit": "Pa", "range_min": None, "range_max": None}, "greater than"),
    ({"bindings": {"elements": "young_modulus_pa"}}, {**MATERIAL, "unit": "1", "value": "12.5"}, "whole-number"),
])
def test_unsupported_or_ambiguous_bindings_are_rejected(updates, parameter, expected):
    check = ProjectTest.model_validate({**CHECK, **updates})
    with pytest.raises(ValueError, match=expected):
        resolve_bindings(check, {"revision": 1, "analysis_type": "structural", "parameters": [parameter]})


def test_invalid_binding_rolls_back_whole_suite_and_does_not_consume_key(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project = client.post("/api/projects", json={**BASE, "parameters": [MATERIAL]}).json()["id"]
        url = f"/api/projects/{project}/analysis-suite"
        headers = {"Idempotency-Key": "binding-validation"}
        invalid = {**CHECK, "label": "invalid", "bindings": {"width_m": "missing property"}}
        failed = client.post(url, json={"expected_revision": 1, "tests": [CHECK, invalid]}, headers=headers)
        assert failed.status_code == 422
        assert client.get(f"/api/projects/{project}/analysis").json()["runs"] == []
        assert client.post(url, json={"expected_revision": 1, "tests": [CHECK]}, headers=headers).status_code == 202


def test_old_rows_migrate_with_immutable_literal_definitions_and_idempotency(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json=BASE).json()["id"]
        url = f"/api/projects/{project}/analysis"
        spec = {"expected_revision": 1, "label": "prior literal study", "adapter": "structural_beam",
                "inputs": {**SHAPE, "young_modulus_pa": 100e9}}
        headers = {"Idempotency-Key": "pre-binding-request"}
        receipt = client.post(url, json=spec, headers=headers).json()
    # Recreate the on-disk column set present immediately before bindings were added.
    with sqlite3.connect(tmp_path/"failureforge.sqlite3") as db:
        db.execute("ALTER TABLE project_runs DROP COLUMN definition")
        db.execute("ALTER TABLE project_runs DROP COLUMN binding_evidence")
        db.execute("UPDATE project_runs SET status='completed',evidence_hash='original-evidence'")
    with TestClient(create_app(tmp_path)) as reopened:
        detail = reopened.get(url+"/"+receipt["id"]).json()
        assert detail["evidence_hash"] == "original-evidence" and detail["binding_evidence"] == {}
        assert detail["definition"] == {k: spec[k] for k in ("label", "adapter", "inputs")}
        assert reopened.post(url, json=spec, headers=headers).json()["id"] == receipt["id"]
