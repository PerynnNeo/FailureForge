import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.contracts import config_hash
from failureforge.scenario_core import BatchDraft, CandidateDraft
from failureforge.scenario_results import recorded_outcome


class FixtureProvider:
    """Replace only inference. The API, persistence, compiler and solver workers are real."""

    def __init__(self):
        self.available = True
        self.packets = []

    def status(self):
        return {"available": self.available, "model": "test-fixture", "digest": "fixture-digest", "detail": "test"}

    def generate(self, packet, digest):
        assert digest == self.status()["digest"]
        self.packets.append(packet)
        if not packet["baseline"]:
            return BatchDraft(candidates=[], clarifications=["Where does the tray support the item?"]), {}
        candidate = CandidateDraft(
            title="Load moved to the outer edge", hypothesis="Moving the load increases bending leverage.",
            operation_id="beam.load.tip_resultant", fact_refs=["task", "baseline.length_m"],
            assumptions=["The operator can position the load at the free end."],
            question="Can the operator put the load there?", shift_ms=None, missing_capability=None)
        impact = candidate.model_copy(update={"title": "What if the item impacts the support?",
                                              "operation_id": None, "missing_capability": "A transient impact model"})
        return BatchDraft(candidates=[candidate, candidate.model_copy(update={"title": "Equivalent wording"}), impact],
                          clarifications=[]), {"attempts": 1}


class BatchFixture(FixtureProvider):
    def generate(self, packet, digest):
        seed, _ = super().generate(packet, digest)
        base = seed.candidates[0]
        cases = [base.model_copy(update={"title": op["label"], "operation_id": op["id"]})
                 for op in packet["operations"]]
        return BatchDraft(candidates=[*cases, cases[0], seed.candidates[-1]], clarifications=[]), {}


def test_batch_comparison_requires_matching_solver_identity():
    run = {"runtime": {"solver": "one"}, "adapter": "structural_beam", "status": "completed",
           "evidence_hash": "checked", "assessment_error": None, "error": None, "result": {"passed": True}}
    other = {**run, "runtime": {"solver": "two"}}
    assert recorded_outcome(run, other)[0] == "inconclusive"
    assert recorded_outcome(other, other, config_hash(run["runtime"]))[0] == "inconclusive"


def checked(response, code):
    assert response.status_code == code, response.text
    return response.json()


def project(client, success_criteria="Deflection within 0.1 mm."):
    return checked(client.post("/api/projects", json={
        "name": "Inspection tray", "entry_stage": "prototype", "analysis_type": "structural",
        "goal": "Help an operator position a part accurately.", "success_criteria": success_criteria}), 201)


def upload(client, base, name, content):
    return checked(client.post(base + "/assets", params={"kind": "requirements", "filename": name}, content=content,
                               headers={"Content-Type": "application/octet-stream"}), 201)


def post(client, path, body, key, code=202):
    return checked(client.post(path, json=body, headers={"Idempotency-Key": key}), code)


def until_completed(read):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        value = read()
        if value["status"] not in {"queued", "running"}:
            assert value["status"] == "completed", value.get("error", value["status"])
            return value
        time.sleep(0.1)
    pytest.fail("Timed out waiting for the ordinary project worker")


def test_upload_review_pair_executes_once_and_preserves_project_evidence(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    provider = FixtureProvider()
    app.state.scenarios.provider = provider
    with TestClient(app) as client:
        p = project(client)
        base = f"/api/projects/{p['id']}"
        scenarios = base + "/scenarios"
        other = f"/api/projects/{project(client)['id']}"
        inputs = {"length_m": 0.2, "width_m": 0.02, "height_m": 0.01, "young_modulus_pa": 70e9,
                  "distributed_load_n_per_m": 25, "max_displacement_m": 0.0001}
        contents = json.dumps({"label": "Our measured support", "adapter": "structural_beam", "inputs": inputs}).encode()
        source = upload(client, base, "station-support.json", contents)
        asset = source["assets"][0]
        rev = {"expected_revision": source["revision"]}
        import_payload = {**rev, "asset_id": asset["id"]}
        imported = post(client, scenarios + "/import-reference", import_payload, "case-import")
        assert post(client, scenarios + "/import-reference", import_payload, "case-import") == imported
        post(client, other + "/scenarios/import-reference", {**import_payload, "expected_revision": 1}, "other-import", 404)
        run_id = imported["ids"][0]
        baseline = until_completed(lambda: checked(client.get(base + "/analysis/" + run_id), 200))
        assert baseline["result"]["passed"] is True and baseline["inputs"]["length_m"] == inputs["length_m"]
        generate = {**rev, "baseline_run_id": run_id, "task": "Operators move this item along the tray."}
        post(client, other + "/scenarios/generate", {**generate, "expected_revision": 1}, "other-case", 404)
        batch_id = post(client, scenarios + "/generate", generate, "case-generation")["id"]
        assert post(client, scenarios + "/generate", generate, "case-generation")["id"] == batch_id
        post(client, scenarios + "/generate", {**generate, "task": "Something else"}, "case-generation", 409)
        batch = until_completed(lambda: checked(client.get(scenarios), 200)["batches"][0])
        assert batch["digest"] == "fixture-digest" and len(provider.packets) == 1
        selected = provider.packets[0]["baseline"]
        assert selected["evidence_hash"] == baseline["evidence_hash"] and selected["run_id"] == run_id
        assert selected["source_asset"] == {"asset_id": asset["id"], "sha256": hashlib.sha256(contents).hexdigest()}
        assert len(batch["candidates"]) == 2  # Equivalent executable definitions were grouped.
        movable, unsupported = [c["id"] for c in batch["candidates"]]
        endpoint = f"{scenarios}/{movable}"
        confirm = {**rev, "confirmed": True}
        checked(client.post(f"{other}/scenarios/{movable}/preview", json={"expected_revision": 1, "confirmed": True}), 404)
        initial = checked(client.post(endpoint + "/preview", json={**rev, "confirmed": False}), 200)
        assert initial["state"] == "needs_information" and initial["variant"]["inputs"]["tip_force_n"] == 5
        post(client, endpoint + "/execute", {**rev, "confirmed": False, "fingerprint": initial["fingerprint"]},
             "premature-run", 409)
        preview = checked(client.post(endpoint + "/preview", json=confirm), 200)
        assert preview["state"] == "ready" and {f["id"] for f in preview["facts"]} == {"task", "baseline.length_m"}
        path = app.state.projects.asset_path(asset["id"])
        path.write_bytes(contents.replace(b"0.02", b"0.03"))
        checked(client.post(endpoint + "/preview", json=confirm), 409)
        path.write_bytes(contents)
        with monkeypatch.context() as patch:
            patch.setattr("failureforge.scenario_core.runtime_identity", lambda adapter: {"implementation": "changed"})
            checked(client.post(endpoint + "/preview", json=confirm), 409)
        missing = checked(client.post(f"{scenarios}/{unsupported}/preview", json=confirm), 200)
        assert missing["state"] == "needs_capability" and missing["variant"] is None
        post(client, f"{scenarios}/{unsupported}/execute", {**confirm, "fingerprint": missing["fingerprint"]},
             "unsupported-run", 409)
        execute = {**confirm, "fingerprint": preview["fingerprint"], "review_note": "Move the same total load."}
        post(client, endpoint + "/execute", {**execute, "fingerprint": "0" * 64}, "wrong-fingerprint", 409)
        with ThreadPoolExecutor(2) as pool:
            receipts = list(pool.map(lambda key: post(client, endpoint + "/execute", execute, key),
                                     ["window-one", "window-two"]))
        receipt = receipts[0]
        assert receipts[1] == receipt and post(client, endpoint + "/execute", execute, "window-one") == receipt
        post(client, endpoint + "/execute", {**execute, "review_note": "Different assumption"}, "another-note", 409)
        cards = checked(client.get(scenarios), 200)["batches"][0]["candidates"]
        assert next(c for c in cards if c["id"] == movable)["review"]["review_note"] == execute["review_note"]
        for identifier in receipt["runs"]:
            until_completed(lambda: checked(client.get(base + "/analysis/" + identifier), 200))
        suite = checked(client.get(base + "/analysis-suite/" + receipt["suite_id"]), 200)["runs"]
        assert [r["id"] for r in suite] == receipt["runs"] and len(suite) == 2
        assert [r["result"]["passed"] for r in suite] == [True, False]
        assert [r["result"]["summary"]["continuous_max_abs_displacement_m"] for r in suite] == pytest.approx(
            [0.000042857143, 0.000114285714])
        assert all(r["evidence_hash"] for r in suite)
        assert len(checked(client.get(base + "/analysis"), 200)["runs"]) == 3
        checked(client.post(endpoint + "/dismiss", json=rev), 409)
        newer = upload(client, base, "note.txt", b"Workholding design revised")
        assert newer["revision"] > rev["expected_revision"]
        checked(client.post(endpoint + "/preview", json=confirm), 409)
        checked(client.post(endpoint + "/preview", json={**confirm, "expected_revision": newer["revision"]}), 409)

    reopened = create_app(tmp_path)
    reopened.state.scenarios.provider = FixtureProvider()
    with TestClient(reopened) as client:
        restored = checked(client.get(scenarios), 200)["batches"][0]
        assert restored["id"] == batch_id and restored["candidates"][0]["execution"] == receipt


def test_planning_without_a_reference_and_provider_availability(tmp_path):
    app = create_app(tmp_path)
    provider = FixtureProvider()
    app.state.scenarios.provider = provider
    with TestClient(app) as client:
        p = project(client)
        base = f"/api/projects/{p['id']}"
        generate = {"expected_revision": 1, "task": "The operator transfers an item."}
        route = base + "/scenarios/generate"
        provider.available = False
        post(client, route, generate, "offline-case", 503)
        provider.available = True
        checked(client.post(route, json=generate), 422)
        post(client, route, generate, "concept-case")
        batch = until_completed(lambda: checked(client.get(base + "/scenarios"), 200)["batches"][0])
        assert batch["candidates"] == [] and batch["clarifications"] == ["Where does the tray support the item?"]
        assert not checked(client.get(base + "/analysis"), 200)["runs"]
        uploaded = upload(client, base, "invalid.json", b'{"adapter":"structural_beam","inputs":{"length_m":1}}')
        post(client, base + "/scenarios/import-reference",
             {"expected_revision": uploaded["revision"], "asset_id": uploaded["assets"][0]["id"]}, "invalid-source", 422)
        assert not checked(client.get(base + "/analysis"), 200)["runs"]


def _beam_reference(client, *, limit=0.0001):
    criteria = "Compare deflections across load positions." if limit is None else "Deflection within 0.1 mm."
    base = "/api/projects/" + project(client, criteria)["id"]
    data = {"adapter": "structural_beam", "inputs": {"length_m": 0.2, "width_m": 0.02, "height_m": 0.01,
            "young_modulus_pa": 70e9, "distributed_load_n_per_m": 25, "max_displacement_m": limit}}
    p = upload(client, base, "shelf.json", json.dumps(data).encode())
    rev = {"expected_revision": p["revision"]}
    receipt = post(client, base + "/scenarios/import-reference", {**rev, "asset_id": p["assets"][0]["id"]}, "reference-run")
    run_id = receipt["ids"][0]
    until_completed(lambda: checked(client.get(base + "/analysis/" + run_id), 200))
    return base, rev, run_id


def test_batch_runs_every_distinct_supported_case_once_and_reports_evidence(tmp_path):
    app = create_app(tmp_path)
    app.state.scenarios.provider = BatchFixture()
    with TestClient(app) as client:
        base, rev, run_id = _beam_reference(client)
        scope = base + "/scenarios"
        request = {**rev, "baseline_run_id": run_id, "task": "Sort several parts on the shelf.", "run_supported": True}
        batch_id = post(client, scope + "/generate", request, "run-all-conditions")["id"]
        group = scope + "/batches/" + batch_id
        batch = until_completed(lambda: checked(client.get(scope), 200)["batches"][0])
        assert batch["run_supported"] and not batch["execution_error"] and batch["target"] == 5
        report = checked(client.get(group + "/results"), 200)
        rows = [r for r in report["rows"] if r["variant_run_id"]]
        assert len(rows) >= 5 and len({r["variant_run_id"] for r in rows}) == len(rows)
        assert len({r["reference_run_id"] for r in rows}) == len({r["suite_id"] for r in rows}) == 1
        assert report["counts"]["blocked"] == 1 and all(r["applied_change"] for r in rows)
        other = "/api/projects/" + project(client)["id"]
        checked(client.get(other + "/scenarios/batches/" + batch_id + "/results"), 404)
        # Automatic, manual and repeated commands converge on the original receipts.
        with ThreadPoolExecutor(2) as pool:
            reports = list(pool.map(lambda key: post(client, group + "/execute-all", rev, key), ["another-window", "batch-retry"]))
        assert all([r["variant_run_id"] for r in item["rows"]] == [r["variant_run_id"] for r in report["rows"]]
                   for item in reports)
        for row in rows:
            until_completed(lambda: checked(client.get(base + "/analysis/" + row["variant_run_id"]), 200))
        final = checked(client.get(group + "/results"), 200)
        assert final["counts"]["assessed"] == len(rows) and final["counts"]["failed"] == 1
        assert final["counts"]["passed"] == len(rows) - 1 and final["counts"]["pending"] == 0
        for row in final["rows"]:
            if row["variant_run_id"]:
                metric = row["measurement"]
                assert metric["unit"] == "mm" and metric["limit"] == 0.1
                assert metric["reference_value"] == pytest.approx(0.042857142857)
                assert (metric["value"] <= metric["limit"]) == (row["state"] == "passed")
        assert len(checked(client.get(base + "/analysis"), 200)["runs"]) == len(rows) + 2
        assert post(client, scope + "/generate", request, "run-all-conditions")["id"] == batch_id
        post(client, scope + "/generate", {**request, "run_supported": False}, "run-all-conditions", 409)
        # A corrupted shared reference invalidates every verdict in this scratch database.
        with app.state.store.connection(True) as db:
            db.execute("UPDATE project_runs SET evidence_hash='bad' WHERE id=?", (rows[0]["reference_run_id"],))
        invalid = checked(client.get(group + "/results"), 200)
        assert invalid["counts"]["assessed"] == 0 and invalid["counts"]["inconclusive"] == len(rows)


def test_measurement_only_batch_returns_both_displacements_without_a_verdict(tmp_path):
    app = create_app(tmp_path)
    app.state.scenarios.provider = FixtureProvider()
    with TestClient(app) as client:
        base, rev, run_id = _beam_reference(client, limit=None)
        scope = base + "/scenarios"
        request = {**rev, "baseline_run_id": run_id, "task": "Move the load to the free end.", "run_supported": True}
        batch_id = post(client, scope + "/generate", request, "compare-deflections")["id"]
        until_completed(lambda: checked(client.get(scope), 200)["batches"][0])
        report_url = scope + "/batches/" + batch_id + "/results"
        row, = (r for r in checked(client.get(report_url), 200)["rows"] if r["variant_run_id"])
        for run in (row["reference_run_id"], row["variant_run_id"]):
            until_completed(lambda: checked(client.get(base + "/analysis/" + run), 200))
        report = checked(client.get(report_url), 200)
        assert report["counts"]["measurement_only"] == 1
        assert report["counts"]["passed"] == report["counts"]["failed"] == report["counts"]["inconclusive"] == 0
        measured, = (r for r in report["rows"] if r["state"] == "measurement_only")
        assert measured["measurement"] == {
            "name": "Maximum deflection", "unit": "mm", "limit": None,
            "reference_value": pytest.approx(0.042857142857), "value": pytest.approx(0.114285714286),
        }


@pytest.mark.parametrize("invalid", [{"summary": {"within_small_deflection_screen": False}},
                                     {"numerical_diagnostics": {"passed": False}}])
def test_failed_validity_checks_never_become_measurement_only(invalid):
    result = {"summary": {"continuous_max_abs_displacement_m": 0.0001}, "passed": None}
    run = {"result": result, "runtime": {}, "status": "completed", "adapter": "structural_beam",
           "error": None, "assessment_error": None, "evidence_hash": "checked"}
    failed = {**run, "result": {**result, **invalid}}
    for pair in ((run, failed), (failed, run)):
        state, _, metric = recorded_outcome(*pair)
        assert state == "inconclusive" and metric is None


def test_auto_run_rechecks_revision_after_local_inference(tmp_path):
    app = create_app(tmp_path)
    waiting, release = Event(), Event()

    class Delayed(BatchFixture):
        def generate(self, packet, digest):
            waiting.set()
            assert release.wait(15)
            return super().generate(packet, digest)

    app.state.scenarios.provider = Delayed()
    with TestClient(app) as client:
        base, rev, run_id = _beam_reference(client)
        scope = base + "/scenarios"
        post(client, scope + "/generate", {**rev, "run_supported": True}, "no-reference", 422)
        created = post(client, scope + "/generate", {**rev, "run_supported": True, "baseline_run_id": run_id,
                       "task": "Sort the parts."}, "racing-revision")
        assert waiting.wait(5)
        try:
            upload(client, base, "changed.txt", b"The shelf was revised.")
        finally:
            release.set()
        batch = until_completed(lambda: checked(client.get(scope), 200)["batches"][0])
        assert batch["execution_error"] and batch["candidates"]
        report = checked(client.get(scope + "/batches/" + created["id"] + "/results"), 200)
        assert report["counts"]["submitted"] == 0 and {r["state"] for r in report["rows"]} == {"stale"}
        assert len(checked(client.get(base + "/analysis"), 200)["runs"]) == 1
