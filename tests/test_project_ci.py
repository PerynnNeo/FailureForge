import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.cli import main, parser
from failureforge.project_ci import Api, execute


class ClientTransport:
    def __init__(self, client):
        self.client = client

    def request(self, method, path, *, timeout, data=None, key=None):
        assert timeout > 0
        response = self.client.request(method, path, json=data, headers={"Idempotency-Key": key} if key else {})
        if response.status_code >= 400:
            raise ValueError(response.text)
        return response.json()


BEAM = {"label": "100 N fixture", "adapter": "structural_beam",
        "inputs": {"length_m": 1., "width_m": .03, "height_m": .04, "young_modulus_pa": 200e9,
                   "tip_force_n": 100., "max_displacement_m": .002, "elements": 2}}


def save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


def test_real_project_suite_rerun_and_observed_regression(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        brief = {"name": "Fixture", "entry_stage": "cad", "analysis_type": "structural",
                 "goal": "Check beam stiffness", "success_criteria": "Tip stays within its recorded limit"}
        project = client.post("/api/projects", json=brief).json()["id"]
        transport = ClientTransport(client)

        def run(*opts):
            args = parser().parse_args(["project-ci", project, "--poll-interval", ".05", *opts])
            return execute(args, api=transport)

        definitions = [BEAM, {**BEAM, "label": "inspection", "inputs": {**BEAM["inputs"], "max_displacement_m": .003}}]
        spec = save(tmp_path/"suite.json", {"tests": definitions})
        first, code = run("--spec", spec, "--idempotency-key", "baseline-batch")
        assert code == 0, first
        assert len(first["runs"]) == 2
        again, _ = run("--spec", spec, "--idempotency-key", "baseline-batch")
        assert again["suite_id"] == first["suite_id"]
        previous = save(tmp_path/"prior.json", first)
        assert client.post(f"/api/projects/{project}", json={**brief, "notes": "Reviewed dimensions", "expected_revision": 1}).status_code == 200
        reattached, code = run("--spec", spec, "--idempotency-key", "baseline-batch", "--expected-revision", "1")
        assert code == 0 and reattached["suite_id"] == first["suite_id"]
        replay, code = run("--rerun", previous, "--expected-revision", "2")
        assert code == 0, replay
        assert replay["project_revision"] == 2 and replay["suite_id"] != first["suite_id"]
        assert [c["outcome"] for c in replay["comparisons"]] == ["unchanged_pass"] * 2
        # A CI report and its immutable suite ID resolve to identical definitions.
        replay_by_id, code = run("--rerun-suite", first["suite_id"], "--idempotency-key", replay["idempotency_key"])
        assert code == 0 and replay_by_id["suite_id"] == replay["suite_id"]
        other = client.post("/api/projects", json={**brief, "name": "Other project"}).json()["id"]
        assert client.get(f"/api/projects/{other}/analysis-suite/{first['suite_id']}").status_code == 404

        weaker = {**BEAM, "inputs": {**BEAM["inputs"], "young_modulus_pa": 50e9}}
        spec = save(tmp_path/"weaker.json", {"tests": [definitions[1], weaker]})
        changed, code = run("--spec", spec, "--baseline", previous)
        assert code == 1, changed
        assert [c["outcome"] for c in changed["comparisons"]] == ["unchanged_pass", "new_failure"]
        assert changed["comparisons"][1]["metric_deltas"]["tip_displacement_m"] > 0
        threshold_change = {**BEAM, "inputs": {**BEAM["inputs"], "max_displacement_m": .1}}
        revised_rule = save(tmp_path/"limit.json", {"tests": [threshold_change, definitions[1]]})
        incomparable, code = run("--spec", revised_rule, "--baseline-suite", first["suite_id"])
        assert code == 2 and incomparable["comparisons"][0]["outcome"] == "not_comparable"

        single = save(tmp_path/"inspect.json", {**BEAM, "inputs": {k: v for k, v in BEAM["inputs"].items() if k != "max_displacement_m"}})
        measuring, code = run("--spec", single)
        assert code == 2 and measuring["runs"][0]["status"] == "completed"
        assert measuring["runs"][0]["passed"] is None
        allowed, code = run("--spec", single, "--allow-measurement-only")
        assert code == 0 and allowed["decision"] == "accepted"
        stale, code = run("--spec", single, "--expected-revision", "1")
        assert code == 2 and stale["suite_id"] is None
        bad = save(tmp_path/"invalid.json", {**BEAM, "inputs": {"length_m": -1}})
        invalid, code = run("--spec", bad)
        assert code == 2 and invalid["runs"][0]["status"] == "invalid"


def test_deadline_keeps_submitted_run_ids_and_does_not_cancel(tmp_path, monkeypatch):
    from failureforge import project_ci
    clock = SimpleNamespace(t=0.)
    monkeypatch.setattr(project_ci, "time", SimpleNamespace(monotonic=lambda: clock.t,
                        sleep=lambda seconds: setattr(clock, "t", clock.t + seconds)))
    args = parser().parse_args(["project-ci", "project_test", "--timeout", ".5", "--spec",
                                save(tmp_path/"one.json", BEAM)])
    methods = []
    class Queued:
        def request(self, method, path, **kwargs):
            methods.append(method)
            if path.endswith("project_test"):
                return {"revision": 1}
            return {"id": "run_test", "suite_id": "suite_test", "label": BEAM["label"], "adapter": BEAM["adapter"],
                    "status": "queued", "project_revision": 1}
    report, code = execute(args, api=Queued())
    assert code == 2 and "deadline" in report["error"]
    assert report["suite_id"] == "suite_test" and report["runs"][0]["id"] == "run_test"
    assert methods.count("POST") == 1 and clock.t == .5


def test_numeric_failure_is_inconclusive_even_when_measurement_only_is_allowed(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project = client.post("/api/projects", json={"name": "Rod", "entry_stage": "model", "analysis_type": "thermal",
                              "goal": "Assess a bounded temperature increase", "success_criteria": "Check the temperature limit"}).json()["id"]
        inputs = {"length_m": 0.1, "area_m2": 0.001, "conductivity_w_mk": 5.0, "left_temperature_k": 290.0,
                  "right_temperature_k": 300.0, "heat_generation_w_m3": 12000.0, "elements": 2,
                  "max_temperature_k": 500.0, "convergence_tolerance_k": 1e-10}
        path = save(tmp_path/"numeric.json", {"label": "underresolved", "adapter": "thermal_rod", "inputs": inputs})
        args = parser().parse_args(["project-ci", project, "--spec", path, "--allow-measurement-only", "--poll-interval", ".05"])
        result, code = execute(args, api=ClientTransport(client))
        assert code == 2 and result["decision"] == "inconclusive"
        record = result["runs"][0]
        assert record["status"] == "completed" and record["passed"] is None
        assert record["assessment_error"] == "Solver numerical checks failed"


def test_cli_outputs_machine_readable_errors_and_restricts_bearer_transport(monkeypatch, capsys):
    monkeypatch.setenv("FAILUREFORGE_API_TOKEN", "test-private-token")
    with pytest.raises(SystemExit) as error:
        main(["project-ci", "project_test", "--api-url", "http://example.test", "--spec", "unused.json"])
    assert error.value.code == 2
    output = capsys.readouterr().out
    assert "test-private-token" not in output and json.loads(output)["decision"] == "inconclusive"
    assert Api("http://127.0.0.1:8000", "local-token").headers["Authorization"] == "Bearer local-token"
