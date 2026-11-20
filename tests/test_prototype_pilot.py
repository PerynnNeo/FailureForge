"""Audit the distinction between a proposed condition and its measured comparison."""
import json
import runpy
from pathlib import Path

import pytest

pilot = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/evaluate_prototype_pilot.py"))


@pytest.fixture
def inputs(tmp_path):
    path = tmp_path / "reference.json"
    ids = ["load", "angle", "wear", "heat", "humidity"]
    path.write_text(json.dumps({
        "prototype": "Test fixture", "checklist_source": "Published test matrix",
        "conditions": [{"id": key, "description": key} for key in ids],
    }), encoding="utf-8")
    lock = pilot["freeze"](path, tmp_path / "lock.json")
    cases = [{"id": "load-case", "draft": {"title": "Double the load"},
              "review": {"reference": {"inputs": {"load": 1}}, "variant": {"inputs": {"load": 2}}},
              "execution": {"suite_id": "suite", "runs": ["left", "right"]}},
             {"id": "tilt-case", "draft": {"title": "Turn the fixture"}},
             {"id": "spare", "draft": {"title": "Retest the reference"}}]
    batch = {"id": "batch", "status": "completed", "created_at": "2099-01-01T00:00:00Z",
             "model": "test-model", "baseline_run_id": "baseline", "task": "Check the fixture",
             "clarifications": ["How worn is the fixture?"], "candidates": cases}
    results = {"batch_id": "batch", "generation_status": "completed", "rows": [
        {"candidate_id": "load-case", "state": "failed", "reason": "Limit exceeded", "measurement": {"value": 3},
         "reference_run_id": "left", "variant_run_id": "right", "suite_id": "suite"},
        {"candidate_id": "tilt-case", "state": "needs_capability", "reason": "Unsupported tilt"},
        {"candidate_id": "spare", "state": "ready", "reason": "Available"}]}
    review = {"reviewer": "Fixture evaluator", "interventions": ["Entered the geometry from the drawing"],
              "conditions": [
                  {"id": "load", "reason": "Group repeated the same two loads", "candidate_id": "load-case",
                   "match": "equivalent", "quote": "Double the load", "origin": "supplied",
                   "controls": {"reference": {"load": 1}, "variant": {"load": 2}}},
                  {"id": "angle", "reason": "Turn on an unspecified axis", "candidate_id": "tilt-case",
                   "match": "related", "quote": "Turn the fixture"},
                  {"id": "wear", "reason": "Only asked about wear", "candidate_id": None,
                   "clarification": "How worn is the fixture?"},
                  {"id": "heat", "reason": "No temperature proposal", "candidate_id": None},
                  {"id": "humidity", "reason": "No humidity proposal", "candidate_id": None}]}
    return path, lock, batch, results, review


def test_assessment_preserves_traceable_levels_and_manual_work(inputs):
    report = pilot["score"](*inputs)
    assert report["coverage"] == {"simulated": 1, "proposed": 0, "related": 1, "clarification_only": 1, "missed": 2}
    assert report["unmatched_candidates"] == ["spare"]
    assert report["conditions"][0]["variant_run_id"] == "right"
    assert report["conditions"][0]["origin"] == "supplied"
    assert report["interventions"] == inputs[-1]["interventions"]
    del inputs[-1]["conditions"][0]["controls"]
    assert pilot["score"](*inputs)["conditions"][0]["coverage"] == "proposed"


def test_lock_is_write_once_and_rejects_post_hoc_reference(inputs):
    path, lock, batch, *_ = inputs
    with pytest.raises(FileExistsError):
        pilot["freeze"](path, path.parent / "lock.json")
    batch["created_at"] = lock["frozen_at"]
    with pytest.raises(ValueError, match="before"):
        pilot["score"](*inputs)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        pilot["score"](*inputs)


def test_dates_use_absolute_instants(inputs):
    _, lock, batch, *_ = inputs
    lock["frozen_at"] = "2026-11-20T12:23:00Z"
    batch["created_at"] = "2026-11-20T20:22:59+08:00"
    with pytest.raises(ValueError, match="before"):
        pilot["score"](*inputs)
    batch["created_at"] = "2026-11-20T20:23:01+08:00"
    assert pilot["score"](*inputs)["condition_count"] == 5


def test_metric_only_requires_reported_measurement_and_validates_nested_control(inputs):
    _, _, batch, results, review = inputs
    plan = batch["candidates"][0]["review"]
    plan["variant"]["inputs"]["patches"] = [{"start": 0.4, "end": 0.6}]
    controls = review["conditions"][0]["controls"]
    controls["variant"]["patches"] = [{"start": 0.4, "end": 0.6}]
    row = results["rows"][0]
    row.update(state="measurement_only", measurement=None)
    assert pilot["score"](*inputs)["conditions"][0]["coverage"] == "proposed"
    row["measurement"] = {"name": "travel", "value": 3, "reference_value": 2, "unit": "mm"}
    assert pilot["score"](*inputs)["conditions"][0]["coverage"] == "simulated"
    controls["variant"]["patches"][0]["end"] = 0.9
    with pytest.raises(ValueError, match="differs"):
        pilot["score"](*inputs)


def test_score_real_api_exports_from_isolated_worker(tmp_path):
    from fastapi.testclient import TestClient
    from failureforge.api import create_app
    from test_scenario_service import FixtureProvider, checked, post, project, until_completed, upload

    checklist = tmp_path / "withheld.json"
    checklist.write_text(json.dumps({"prototype": "Fixture for API contract test", "checklist_source": "test only",
                                     "conditions": [{"id": "private-test-row", "description": "Move load to tip"}]}))
    lock = pilot["freeze"](checklist, tmp_path / "lock.json")
    app = create_app(tmp_path / "pilot-store")
    app.state.scenarios.provider = provider = FixtureProvider()
    with TestClient(app) as client:
        base = "/api/projects/" + project(client)["id"]
        url = base + "/scenarios"
        payload = {"adapter": "structural_beam", "label": "Fixture", "inputs": {
            "length_m": 0.2, "width_m": 0.02, "height_m": 0.01, "young_modulus_pa": 70e9,
            "distributed_load_n_per_m": 25, "max_displacement_m": 0.0001}}
        saved = upload(client, base, "fixture.json", json.dumps(payload).encode())
        revision = {"expected_revision": saved["revision"]}
        receipt = post(client, url + "/import-reference", {**revision, "asset_id": saved["assets"][0]["id"]}, "pilot-import")
        baseline = receipt["ids"][0]
        until_completed(lambda: checked(client.get(base + "/analysis/" + baseline), 200))
        post(client, url + "/generate", {**revision, "task": "Position a part along the tray",
             "baseline_run_id": baseline, "run_supported": True}, "pilot-generate")
        batch = until_completed(lambda: checked(client.get(url), 200)["batches"][0])
        candidate = next(case for case in batch["candidates"] if case["execution"])
        for run in candidate["execution"]["runs"]:
            until_completed(lambda: checked(client.get(base + "/analysis/" + run), 200))
        results = checked(client.get(url + "/batches/" + batch["id"] + "/results"), 200)
    plan = candidate["review"]
    controls = {role: {key: plan[role]["inputs"][key] for key in plan["diff"]
                       if key in plan[role]["inputs"]} for role in ("reference", "variant")}
    review = {"reviewer": "Contract test", "interventions": [], "conditions": [{
        "id": "private-test-row", "candidate_id": candidate["id"], "match": "equivalent",
        "quote": "outer edge", "reason": "same fixed load moved to the tip", "controls": controls}]}
    report = pilot["score"](checklist, lock, batch, results, review)
    assert report["conditions"][0]["candidate_state"] == "failed"
    assert report["coverage"]["simulated"] == 1
    assert report["digest"] == "fixture-digest"
    assert report["candidates"][0]["operation_id"] == "beam.load.tip_resultant"
    assert "private-test-row" not in json.dumps(provider.packets)


@pytest.mark.parametrize(("problem", "error"), [
    ("wrong_quote", "absent"), ("wrong_control", "differs"), ("confounded", "additional"), ("wrong_run", "matching"),
    ("wrong_batch", "different batches"), ("generation_error", "completed generation"),
    ("missing_condition", "every independent"), ("missing_result", "same candidates"),
])
def test_rejects_unsupported_evidence_claims(inputs, problem, error):
    _, _, batch, results, review = inputs
    matched = review["conditions"][0]
    if problem == "wrong_quote":
        matched["quote"] = "A reviewer wrote this after the run"
    elif problem == "wrong_control":
        matched["controls"]["variant"]["load"] = 20
    elif problem == "confounded":
        batch["candidates"][0]["review"]["variant"]["inputs"]["angle"] = 10
    elif problem == "wrong_run":
        results["rows"][0]["reference_run_id"] = "unrelated-reference"
    elif problem == "wrong_batch":
        results["batch_id"] = "other-batch"
    elif problem == "generation_error":
        batch["status"] = "error"
    elif problem == "missing_condition":
        review["conditions"].pop()
    elif problem == "missing_result":
        results["rows"].pop()
    with pytest.raises(ValueError, match=error):
        pilot["score"](*inputs)
