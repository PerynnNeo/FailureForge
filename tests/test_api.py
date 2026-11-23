import json

from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.simulation.synthetic import SyntheticRunner
from failureforge.worker.engine import Worker


def test_api_runs_without_gpu_and_rejects_unqualified_robot_execution(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["runtime_mode"] == "offline"
        assert not health["readiness"]["qualified"]
        assert "RTX 5090" not in health["readiness"]["reason"]
        response = client.post("/api/campaigns", json={"backend": "libero"}, headers={"Idempotency-Key": "test-live-key"})
        assert response.status_code == 409
        catalog = client.get("/api/catalog").json()
        assert catalog["policy"]["revision"]
        assert catalog["qualification"] == health["readiness"]


def test_api_synthetic_journey_and_export(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        body = {"backend": "synthetic", "candidate_count": 8}
        headers = {"Idempotency-Key": "test-diagnostic-key"}
        created = client.post("/api/campaigns", json=body, headers=headers)
        assert created.status_code == 202
        assert client.post("/api/campaigns", json=body, headers=headers).json() == created.json()
        worker = Worker(app.state.store, app.state.artifacts, SyntheticRunner())
        assert worker.run_once()
        assert worker.last_error is None
        campaign = client.get(f"/api/campaigns/{created.json()['campaign_id']}").json()
        assert campaign["budget"]["completed"] == 18
        case = campaign["cases"][0]
        trace = client.get(f"/api/episodes/{case['episodes'][0]['id']}/trace")
        assert trace.status_code == 200
        assert trace.json()["backend"] == "synthetic"
        exported = client.get(f"/api/cases/{case['id']}/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"] == "application/zip"
        rerun = client.post(f"/api/cases/{case['id']}/rerun", json={"allowance": 2}, headers={"Idempotency-Key": "test-fresh-rerun"})
        assert rerun.status_code == 202
        worker.run_once()
        assert worker.last_error is None


def test_validation_errors_are_json_safe(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/campaigns", content='{"backend":"synthetic","domain":{"main_camera_dx_m":[NaN,0.04]}}', headers={"Content-Type": "application/json", "Idempotency-Key": "bad-bound-key"})
        assert response.status_code == 422
        assert response.json()["detail"]
        assert client.post("/api/campaigns", json={"backend": "synthetic"}).status_code == 422
        assert client.get("/api/cases/absent").status_code == 404


def test_auth_and_origin_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILUREFORGE_API_TOKEN", "test-token")
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/health").status_code == 401
        assert client.get("/api/health", headers={"Authorization": "Bearer test-token"}).status_code == 200
        response = client.post("/api/campaigns", json={"backend": "synthetic"}, headers={"Authorization": "Bearer test-token", "Idempotency-Key": "origin-test-key", "Origin": "https://untrusted.example"})
        assert response.status_code == 403


def test_authenticated_cors_preflight_does_not_require_bearer_token(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILUREFORGE_API_TOKEN", "test-token")
    origin = "http://127.0.0.1:5173"
    with TestClient(create_app(tmp_path)) as client:
        response = client.options("/api/campaigns", headers={"Origin": origin,
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Authorization, Content-Type, Idempotency-Key"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert client.post("/api/campaigns", json={"backend": "synthetic"}, headers={"Origin": origin}).status_code == 401
        assert client.options("/api/campaigns").status_code == 401
        denied = client.options("/api/campaigns", headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"})
        assert denied.status_code != 200
        denied_header = client.options("/api/campaigns", headers={"Origin": origin,
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "X-Unapproved-Header"})
        assert denied_header.status_code == 400


def test_public_campaign_and_case_responses_hide_lease_tokens(tmp_path):
    app = create_app(tmp_path)
    store = app.state.store
    created = store.create_campaign({"backend": "synthetic", "candidate_count": 8}, "redaction-campaign")
    job = store.claim_job("synthetic", "redaction-worker")
    token = job["lease_token"]
    request = {"state_id": 0, "seed": 0, "condition": "reference", "scene_change": {"main_camera_dx_m": 0, "light_scale": 1}}
    episode = store.reserve_episode(job["id"], token, "baseline", request)
    store.complete_episode(job["id"], token, episode, {"outcome": "success", "backend": "synthetic"},
        {"episode_id": episode, "lease_token": token, "relative_dir": f"episodes/{episode}_{token}", "files": []})
    case_id = store.save_case(job["id"], token, {"status": "observed", "scene_change": request["scene_change"], "episode_ids": [episode]})
    with TestClient(app) as client:
        for path in ("/api/campaigns", f"/api/campaigns/{created['campaign_id']}", f"/api/jobs/{job['id']}", f"/api/cases/{case_id}"):
            response = client.get(path)
            assert response.status_code == 200
            assert "lease_token" not in response.text
            assert "relative_dir" not in response.text
            assert token not in response.text
    # Internal state must keep the token and artifact identity for fencing/reuse.
    assert store.get_job(job["id"])["lease_token"] == token
    assert store.get_case(case_id)["episodes"][0]["artifact_manifest"]["lease_token"] == token
