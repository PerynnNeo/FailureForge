import time

import pytest

from failureforge.contracts import CampaignSpec
from failureforge.persistence import BudgetExceeded, Conflict, LeaseLost, Store


def setup(tmp_path):
    store = Store(tmp_path / "store.db")
    created = store.create_campaign(CampaignSpec(backend="synthetic", candidate_count=8), "create-key")
    job = store.claim_job("synthetic", "test-worker")
    return store, created, job


def request(state=0, key="episode-key"):
    return {"state_id": state, "seed": 10, "scene_change": {"main_camera_dx_m": 0, "light_scale": 1}, "request_key": key}


def test_submission_idempotency_binds_input(tmp_path):
    store, created, job = setup(tmp_path)
    assert store.create_campaign(CampaignSpec(backend="synthetic", candidate_count=8), "create-key") == created
    with pytest.raises(Conflict):
        store.create_campaign(CampaignSpec(backend="synthetic", candidate_count=16), "create-key")
    assert len(store.list_campaigns()) == 1
    assert store.claim_job("synthetic", "second-worker") is None


def test_reserved_work_counts_against_phase_limit(tmp_path):
    store, created, job = setup(tmp_path)
    store.reserve_episode(job["id"], job["lease_token"], "baseline", request())
    store.reserve_episode(job["id"], job["lease_token"], "baseline", request(1, "second"))
    with pytest.raises(BudgetExceeded):
        store.reserve_episode(job["id"], job["lease_token"], "baseline", request())
    assert store.get_campaign(created["campaign_id"])["budget"]["reserved"] == 2


def test_expired_worker_cannot_publish_and_started_attempt_remains_charged(tmp_path):
    store, created, job = setup(tmp_path)
    episode_id = store.reserve_episode(job["id"], job["lease_token"], "baseline", request())
    with store.connection(True) as db:
        db.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() - 1, job["id"]))
    store.recover_expired()
    assert store.get_job(job["id"])["status"] == "interrupted"
    store.resume_job(job["id"])
    replacement = store.claim_job("synthetic", "replacement")
    assert replacement["lease_token"] != job["lease_token"]
    with pytest.raises(LeaseLost):
        store.complete_episode(job["id"], job["lease_token"], episode_id, {"outcome": "success"}, {})
    budget = store.get_campaign(created["campaign_id"])["budget"]
    assert (budget["attempted"], budget["completed"], budget["reserved"], budget["errors"]) == (1, 0, 0, 1)


def test_cancellation_is_idempotent_and_prevents_new_reservations(tmp_path):
    store, created, job = setup(tmp_path)
    store.request_cancel(job["id"])
    store.request_cancel(job["id"])
    assert store.cancel_requested(job["id"], job["lease_token"])
    with pytest.raises(Conflict):
        store.reserve_episode(job["id"], job["lease_token"], "search", request())
    store.finish_job(job["id"], job["lease_token"], "succeeded")
    assert store.get_job(job["id"])["status"] == "cancelled"


def test_queued_cancel_never_starts(tmp_path):
    store = Store(tmp_path / "store.db")
    created = store.create_campaign(CampaignSpec(backend="synthetic"), "queue-key")
    store.request_cancel(created["job_id"])
    assert store.claim_job("synthetic", "worker") is None


def test_backup_reopens_with_completed_metadata(tmp_path):
    store, created, _ = setup(tmp_path)
    destination = tmp_path / "backup.db"
    store.backup(destination)
    assert Store(destination).get_campaign(created["campaign_id"])["id"] == created["campaign_id"]


def complete_scored_episode(store, job, candidate_id, state, scene, *, phase="search", condition="changed", suffix=""):
    episode_request = {**request(state, f"{candidate_id}-{state}-{suffix}"), "scene_change": scene,
                       "candidate_id": candidate_id, "phase": phase, "condition": condition}
    episode_id = store.reserve_episode(job["id"], job["lease_token"], phase, episode_request)
    store.complete_episode(job["id"], job["lease_token"], episode_id, {"outcome": "horizon_exhausted"},
        {"episode_id": episode_id, "lease_token": job["lease_token"], "relative_dir": "episodes/test", "files": []})
    return episode_id


@pytest.mark.parametrize("mismatch", ["candidate_id", "scene", "phase", "condition"])
def test_candidate_cannot_score_unrelated_completed_evidence(tmp_path, mismatch):
    store, created, job = setup(tmp_path)
    scene = {"main_camera_dx_m": 0.01, "light_scale": 1.1}
    candidate_id = store.add_candidate(job["id"], job["lease_token"], 0, scene, "test")
    stored_candidate = candidate_id if mismatch != "candidate_id" else "another-candidate"
    stored_scene = scene if mismatch != "scene" else {"main_camera_dx_m": 0.02, "light_scale": 1.1}
    phase = "baseline" if mismatch == "phase" else "search"
    condition = "reference" if mismatch == "condition" else "changed"
    episode_ids = [complete_scored_episode(store, job, stored_candidate, state, stored_scene,
                                          phase=phase, condition=condition) for state in (0, 1)]
    with pytest.raises(Conflict, match="Candidate evidence must match"):
        store.complete_candidate(job["id"], job["lease_token"], candidate_id, episode_ids, 1)
    assert store.list_candidates(created["campaign_id"])[0]["status"] == "proposed"


def test_completed_candidate_pair_is_immutable_but_idempotent(tmp_path):
    store, created, job = setup(tmp_path)
    scene = {"main_camera_dx_m": 0.01, "light_scale": 1.1}
    candidate_id = store.add_candidate(job["id"], job["lease_token"], 0, scene, "test")
    first = [complete_scored_episode(store, job, candidate_id, state, scene, suffix="first") for state in (0, 1)]
    second = [complete_scored_episode(store, job, candidate_id, state, scene, suffix="second") for state in (0, 1)]
    store.complete_candidate(job["id"], job["lease_token"], candidate_id, first, 1)
    store.complete_candidate(job["id"], job["lease_token"], candidate_id, first, 1)
    with pytest.raises(Conflict, match="immutable"):
        store.complete_candidate(job["id"], job["lease_token"], candidate_id, second, 1)
    assert store.list_candidates(created["campaign_id"])[0]["episode_ids"] == first


def test_targeted_claim_never_consumes_an_unrelated_job(tmp_path):
    store = Store(tmp_path / "store.db")
    first = store.create_campaign(CampaignSpec(backend="synthetic"), "first")
    second = store.create_campaign(CampaignSpec(backend="synthetic"), "second")
    assert store.claim_job("synthetic", "worker", target_job_id="absent") is None
    assert store.claim_job("libero", "worker", target_job_id=second["job_id"]) is None
    claimed = store.claim_job("synthetic", "worker", target_job_id=second["job_id"])
    assert claimed["id"] == second["job_id"]
    assert store.get_job(first["job_id"])["status"] == "queued"
