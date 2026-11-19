import numpy as np
import pytest

from failureforge.artifacts import ArtifactStore, inspect_bundle
from failureforge.persistence import Store
from failureforge.simulation.synthetic import SyntheticRunner
from failureforge.worker import Worker


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / "workbench.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    return store, artifacts


def create(store, **kwargs):
    return store.create_campaign({"backend": "synthetic", "candidate_count": 8, "method": "sobol", **kwargs}, "campaign")


def test_full_diagnostic_journey_search_reduce_confirm_rerun_export(system):
    store, artifacts = system
    # This fixed diagnostic seed has a smaller witness in the declared grid.
    # The equally valid no-improvement branch has its own regression below.
    created = create(store, seed=1)
    worker = Worker(store, artifacts, SyntheticRunner(), backend="synthetic")
    assert worker.run_once()
    assert worker.last_error is None
    campaign = store.get_campaign(created["campaign_id"])
    assert campaign["status"] == "succeeded"
    assert len(campaign["candidates"]) == 8
    assert campaign["budget"]["phases"]["search"]["completed"] == 16
    assert campaign["budget"]["phases"]["baseline"]["completed"] == 2
    assert len(campaign["cases"]) == 1
    case = campaign["cases"][0]
    assert case["evidence_kind"] == "synthetic_diagnostic"
    assert case["failure_state_ids"]
    frozen_failures = list(case["failure_state_ids"])
    incomplete = []
    for episode in campaign["episodes"]:
        assert episode["request"]["backend"] == "synthetic"
        if episode["status"] != "completed":
            incomplete.append(episode)
            assert episode["status"] == "error"
            assert episode["outcome"] in {"load_error", "renderer_error", "model_error", "numerical_error", "worker_lost", "artifact_error"}
            assert episode["result"].get("error")
            assert episode["artifact_manifest"] is None
            continue
        assert episode["result"]["backend"] == "synthetic"
        artifacts.verify_episode(episode["artifact_manifest"])
        assert not any(item["role"] in {"main_video", "wrist_video"} for item in episode["artifact_manifest"]["files"])
    assert campaign["budget"]["attempted"] == campaign["budget"]["completed"] + len(incomplete)
    assert len(incomplete) <= 2
    assert campaign["budget"]["retries"] <= 2

    store.enqueue_case_job(case["id"], "reduce", "reduce")
    assert worker.run_once()
    assert worker.last_error is None
    case = store.get_case(case["id"])
    assert case["failure_state_ids"] == frozen_failures
    assert case["status"] == "reproduced"
    assert case["reduced"] is True
    assert len(case["reduction_history"]) <= 12
    assert all(pair["reference_outcome"] == "success" for pair in case["reduction_final_pairs"])
    assert set(frozen_failures) <= {pair["state_id"] for pair in case["pairs"] if pair["changed_outcome"] != "success"}

    store.enqueue_case_job(case["id"], "confirm", "confirm")
    assert worker.run_once()
    assert worker.last_error is None
    case = store.get_case(case["id"])
    summary = case["confirmation_summary"]
    assert summary["denominator"] == 10
    assert sum(summary[key] for key in ("both_success", "induced_failure", "both_failure", "changed_only_success")) == 10
    assert {pair["state_id"] for pair in case["confirmation_pairs"]}.isdisjoint({0, 1})
    assert all(pair["reference_episode_id"] != pair["changed_episode_id"] for pair in case["confirmation_pairs"])

    previous_ids = set(case["episode_ids"])
    store.enqueue_case_job(case["id"], "rerun", "rerun", {"allowance": 2})
    assert worker.run_once()
    assert worker.last_error is None
    case = store.get_case(case["id"])
    assert len(set(case["episode_ids"]) - previous_ids) == 2
    assert case["reruns"][0]["reproduced"]
    campaign = store.get_campaign(created["campaign_id"])
    assert campaign["budget"]["phases"]["reduction"]["completed"] <= 32
    assert campaign["budget"]["phases"]["confirmation"]["completed"] == 20
    assert campaign["budget"]["phases"]["rerun"]["completed"] == 2
    bundle = artifacts.export_case(case, campaign)
    verified = inspect_bundle(bundle)
    assert verified["valid"] is True
    assert verified["backend"] == "synthetic"
    assert verified["evidence_kind"] == "synthetic_diagnostic"
    assert not worker.run_once()


def test_bounded_reduction_can_reproduce_without_finding_improvement(system):
    store, artifacts = system
    created = create(store, seed=1729)
    worker = Worker(store, artifacts, SyntheticRunner())
    assert worker.run_once()
    assert worker.last_error is None
    case = store.get_campaign(created["campaign_id"])["cases"][0]
    assert case["failure_state_ids"] == [0, 1]
    original = dict(case["scene_change"])
    store.enqueue_case_job(case["id"], "reduce", "no-improvement-reduce")
    assert worker.run_once()
    assert worker.last_error is None
    case = store.get_case(case["id"])
    assert case["status"] == "reproduced"
    assert case["reduced"] is False
    assert case["scene_change"] == original
    assert len(case["reduction_history"]) == 12
    assert not any(proposal["accepted"] for proposal in case["reduction_history"])
    # A smaller proposal still fails state0, but state1 now succeeds. Retaining
    # that proposal would silently change the declared two-state witness.
    disagreements = [proposal for proposal in case["reduction_history"]
                     if set(proposal["outcomes"].values()) == {"success", "horizon_exhausted"}]
    assert disagreements
    assert all(not proposal["preserves_witness"] for proposal in disagreements)
    assert store.get_campaign(created["campaign_id"])["budget"]["phases"]["reduction"]["completed"] == 32


def test_completed_search_without_failure_is_successful(system):
    store, artifacts = system
    created = create(store, domain={"main_camera_dx_m": [-0.001, 0.001], "light_scale": [0.99, 1.01]})
    worker = Worker(store, artifacts, SyntheticRunner())
    worker.run_once()
    campaign = store.get_campaign(created["campaign_id"])
    assert worker.last_error is None
    assert campaign["status"] == "succeeded"
    assert campaign["cases"] == []
    assert all(candidate["score"] == 0 for candidate in campaign["candidates"])


def test_reference_failure_stops_search_without_creating_false_case(system):
    store, artifacts = system
    created = create(store, state_ids=[6, 13], confirmation_state_ids=list(range(14, 24)))
    worker = Worker(store, artifacts, SyntheticRunner())
    worker.run_once()
    campaign = store.get_campaign(created["campaign_id"])
    assert campaign["status"] == "failed"
    assert "Reference screening" in worker.last_error
    assert not campaign["candidates"]
    assert not campaign["cases"]
    assert campaign["budget"]["attempted"] == 2


class CrashOnCall(SyntheticRunner):
    def __init__(self, crash_at):
        self.calls = 0
        self.crash_at = crash_at

    def run(self, request, output_dir, cancelled):
        self.calls += 1
        if self.calls == self.crash_at:
            raise SystemExit("simulated process death")
        return super().run(request, output_dir, cancelled)


def expire_and_resume(store, job_id):
    with store.connection(True) as db:
        db.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (job_id,))
    store.recover_expired()
    assert store.get_job(job_id)["status"] == "interrupted"
    store.resume_job(job_id)


def test_partial_candidate_resume_reuses_first_state_and_saved_proposal(system):
    store, artifacts = system
    created = create(store)
    with pytest.raises(SystemExit):
        Worker(store, artifacts, CrashOnCall(4)).run_once()
    before = store.get_campaign(created["campaign_id"])
    assert len(before["candidates"]) == 1
    assert before["candidates"][0]["score"] is None
    proposal = before["candidates"][0]["scene_change"]
    completed_ids = {row["id"] for row in before["episodes"] if row["status"] == "completed"}
    assert len(completed_ids) == 3
    expire_and_resume(store, created["job_id"])
    worker = Worker(store, artifacts, SyntheticRunner())
    worker.run_once()
    assert worker.last_error is None
    after = store.get_campaign(created["campaign_id"])
    assert after["candidates"][0]["scene_change"] == proposal
    assert completed_ids <= {row["id"] for row in after["episodes"] if row["status"] == "completed"}
    assert after["budget"]["completed"] == 18
    assert after["budget"]["attempted"] == 19
    assert sum(row["outcome"] == "worker_lost" for row in after["episodes"]) == 1


def test_corrupt_completed_artifact_blocks_resume(system):
    store, artifacts = system
    created = create(store)
    with pytest.raises(SystemExit):
        Worker(store, artifacts, CrashOnCall(4)).run_once()
    before = store.get_campaign(created["campaign_id"])
    completed = next(row for row in before["episodes"] if row["status"] == "completed")
    manifest = completed["artifact_manifest"]
    target = artifacts.root / manifest["relative_dir"] / manifest["files"][0]["path"]
    target.write_text("tampered", encoding="utf-8")
    expire_and_resume(store, created["job_id"])
    worker = Worker(store, artifacts, SyntheticRunner())
    worker.run_once()
    assert "checksum" in worker.last_error.lower()
    after = store.get_campaign(created["campaign_id"])
    assert after["status"] == "failed"
    assert after["budget"]["attempted"] == 4


def test_cancel_during_episode_stops_next_reservation(system):
    store, artifacts = system
    created = create(store)

    class CancellingRunner(SyntheticRunner):
        def run(self, request, output_dir, cancelled):
            store.request_cancel(created["job_id"])
            return super().run(request, output_dir, cancelled)

    worker = Worker(store, artifacts, CancellingRunner())
    worker.run_once()
    campaign = store.get_campaign(created["campaign_id"])
    assert campaign["status"] == "cancelled"
    assert campaign["budget"]["attempted"] == 1
    assert campaign["episodes"][0]["outcome"] == "cancelled"
    assert not campaign["cases"]


@pytest.mark.parametrize("failures,expected_status,expected_attempts", [(2, "succeeded", 20), (99, "failed", 3)])
def test_shared_infrastructure_retry_allowance(system, failures, expected_status, expected_attempts):
    store, artifacts = system
    created = create(store)

    class FlakyRunner(SyntheticRunner):
        calls = 0

        def run(self, request, output_dir, cancelled):
            self.calls += 1
            if self.calls <= failures:
                raise RuntimeError("Intentional model transport fault")
            return super().run(request, output_dir, cancelled)

    worker = Worker(store, artifacts, FlakyRunner())
    worker.run_once()
    campaign = store.get_campaign(created["campaign_id"])
    assert campaign["status"] == expected_status
    assert campaign["budget"]["attempted"] == expected_attempts
    assert all(row["outcome"] == "model_error" for row in campaign["episodes"] if row["status"] == "error")


def test_backend_is_never_silently_replaced(system):
    store, artifacts = system
    with pytest.raises(ValueError, match="does not match"):
        Worker(store, artifacts, SyntheticRunner(), backend="libero")
    created = store.create_campaign({"backend": "libero", "candidate_count": 8}, "real-campaign")
    assert not Worker(store, artifacts, SyntheticRunner(), backend="synthetic").run_once()
    assert store.get_job(created["job_id"])["status"] == "queued"


def test_targeted_worker_does_not_claim_a_different_queued_job(system):
    store, artifacts = system
    created = create(store)
    worker = Worker(store, artifacts, SyntheticRunner())
    assert not worker.run_once(target_job_id="absent")
    assert store.get_job(created["job_id"])["status"] == "queued"


@pytest.mark.parametrize("bad_result", [None,
    {"outcome": "success", "backend": "libero", "task_success": True, "steps": 4, "elapsed_seconds": 0.2},
    {"outcome": "success", "backend": "synthetic", "task_success": True, "steps": 4, "elapsed_seconds": float("nan")},
])
def test_invalid_runner_result_cannot_become_scientific_evidence(system, bad_result):
    store, artifacts = system
    created = create(store)

    class InvalidRunner(SyntheticRunner):
        def run(self, request, output_dir, cancelled):
            return bad_result

    worker = Worker(store, artifacts, InvalidRunner())
    worker.run_once()
    campaign = store.get_campaign(created["campaign_id"])
    assert campaign["status"] == "failed"
    assert campaign["budget"]["completed"] == 0
    assert campaign["budget"]["attempted"] == 3
    assert all(row["outcome"] == "numerical_error" for row in campaign["episodes"])
    assert not campaign["cases"]


def test_invalid_scene_is_preserved_and_not_retried(system):
    store, artifacts = system
    created = create(store)

    class InvalidSceneError(RuntimeError):
        code = "invalid_scene"

    class InvalidRunner(SyntheticRunner):
        def run(self, request, output_dir, cancelled):
            raise InvalidSceneError("Predeclared render validity gate rejected scene")

    worker = Worker(store, artifacts, InvalidRunner())
    worker.run_once()
    campaign = store.get_campaign(created["campaign_id"])
    assert campaign["status"] == "failed"
    assert campaign["budget"]["attempted"] == 1
    assert campaign["episodes"][0]["outcome"] == "invalid_scene"
    assert not campaign["cases"]


def test_synthetic_numerical_artifacts_are_nonexecutable_and_explicit(tmp_path):
    result = SyntheticRunner().run({"state_id": 0, "seed": 41, "scene_change": {"main_camera_dx_m": 0, "light_scale": 1}}, tmp_path)
    assert result["evidence_kind"] == "synthetic_diagnostic"
    assert "No robot simulation" in result["metadata"]["notice"]
    with np.load(tmp_path / "traces.npz", allow_pickle=False) as arrays:
        assert len(arrays["timestamps"]) == result["steps"] + 1
        assert arrays["diagnostic_state"].shape == (result["steps"] + 1, 3)
        assert all(not arrays[name].dtype.hasobject for name in arrays.files)
    assert not list(tmp_path.glob("*.mp4"))
