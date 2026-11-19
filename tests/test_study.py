import json

import pytest

from failureforge import cli
from failureforge.persistence import Store
from failureforge.simulation.synthetic import SyntheticRunner
from failureforge.study import StudyManifest, study_report
from failureforge.worker import Worker


def campaign(store, method, seed=1, **settings):
    spec = {"backend": "synthetic", "method": method, "candidate_count": 8, "seed": seed, **settings}
    return store.create_campaign(spec, f"{method}-{seed}")["campaign_id"]


def test_cli_distinguishes_no_find_incomplete_and_missing(tmp_path, capsys):
    store, artifacts = cli.services(tmp_path)
    domain = {"main_camera_dx_m": [-0.001, 0.001], "light_scale": [0.99, 1.01]}
    random = campaign(store, "random", domain=domain)
    worker = Worker(store, artifacts, SyntheticRunner())
    assert worker.run_once() and worker.last_error is None
    sobol = campaign(store, "sobol", domain=domain)
    path = tmp_path / "study.json"
    path.write_text(json.dumps({"backend": "synthetic", "seeds": [1, 2],
                                "campaigns": {"random": [random, None], "sobol": [sobol, None]}}), encoding="utf-8")
    args = ["--data-dir", str(tmp_path), "study-report", "--manifest", str(path)]
    cli.main(args)
    report = json.loads(capsys.readouterr().out)
    assert report["evidence_kind"] == "synthetic_diagnostic"
    assert report["fully_matched_completed_seeds"] == []
    result, missing, queued, _ = report["runs"]
    assert result["outcome"] == "no_find"
    assert result["completed_candidates"] == 8
    assert result["baseline_attempts"] == 2 and result["search_attempts"] == 16
    assert result["first_failing_candidate_number"] is None
    assert result["search_attempts_to_first_failing_candidate"] is None
    assert missing["outcome"] == "missing"
    assert queued["outcome"] == "incomplete" and queued["search_status"] == "queued"
    assert report["methods"][0] == {"method": "random", "planned": 2, "completed": 1, "found": 0,
                                     "no_find": 1, "incomplete": 0, "missing": 1}
    cli.main([*args, "--format", "markdown"])
    output = capsys.readouterr().out
    assert "synthetic_diagnostic" in output and random in output and "no_find" in output
    assert store.get_campaign(sobol)["jobs"][0]["status"] == "queued"


def test_first_failure_uses_completed_pair_and_charges_retry(tmp_path):
    class RetryFirstSearch(SyntheticRunner):
        injected_error = False

        def run(self, request, output_dir, cancelled):
            if request["phase"] == "search" and not self.injected_error:
                self.injected_error = True
                raise RuntimeError("test interruption")
            return super().run(request, output_dir, cancelled)

    store, artifacts = cli.services(tmp_path)
    sobol = campaign(store, "sobol")
    worker = Worker(store, artifacts, RetryFirstSearch())
    assert worker.run_once() and worker.last_error is None
    case = store.get_campaign(sobol)["cases"][0]
    store.enqueue_case_job(case["id"], "reduce", "queued-follow-up")
    manifest = StudyManifest(backend="synthetic", seeds=[1], campaigns={"sobol": [sobol], "random": [None]})
    run = study_report(store.path, manifest)["runs"][0]
    assert run["outcome"] == "found" and run["search_status"] == "succeeded"
    assert run["attempt_errors_by_outcome"] == {"model_error": 1}
    assert run["search_attempts_to_first_failing_candidate"] == 2 * run["first_failing_candidate_number"] + 1
    assert run["search_attempts"] == 17


@pytest.mark.parametrize("change,expected", [
    ({"backend": "libero"}, "backend, method and seed"),
    ({"seed": 2}, "backend, method and seed"),
    ({"candidate_count": 16}, "candidate_count"),
    ({"domain": {"light_scale": [0.9, 1.1]}}, "domain"),
    ({"state_ids": [12, 13]}, "state_ids"),
])
def test_rejects_mismatched_campaigns(tmp_path, change, expected):
    store = Store(tmp_path / "study.sqlite3")
    random = campaign(store, "random")
    sobol = campaign(store, "sobol", **change)
    manifest = StudyManifest(backend="synthetic", seeds=[1], campaigns={"random": [random], "sobol": [sobol]})
    with pytest.raises(ValueError, match=expected):
        study_report(store.path, manifest)


def test_manifest_rejects_duplicate_assignments_and_wrong_row_lengths():
    with pytest.raises(ValueError, match="unique"):
        StudyManifest(backend="synthetic", seeds=[1], campaigns={"random": ["a"], "sobol": ["a"]})
    with pytest.raises(ValueError, match="for each seed"):
        StudyManifest(backend="synthetic", seeds=[1, 2], campaigns={"random": [None], "sobol": [None, None]})


def test_rejects_changed_recorded_robot_environment(tmp_path):
    store = Store(tmp_path / "study.sqlite3")
    assignments = {}
    for method in ("random", "sobol"):
        identifier = campaign(store, method, backend="libero")
        assignments[method] = [identifier]
        job = store.claim_job("libero", "test-worker")
        episode = store.reserve_episode(job["id"], job["lease_token"], "baseline", {"state_id": 0})
        store.complete_episode(job["id"], job["lease_token"], episode,
                               {"outcome": "success", "elapsed_seconds": 1, "metadata": {"environment_fingerprint": method}},
                               {"episode_id": episode, "lease_token": job["lease_token"], "files": []})
        store.finish_job(job["id"], job["lease_token"], "cancelled")
    manifest = StudyManifest(backend="libero", seeds=[1], campaigns=assignments)
    with pytest.raises(ValueError, match="fingerprints"):
        study_report(store.path, manifest)
