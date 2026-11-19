import hashlib
import json

from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.simulation.profile import json_hash


def fixture(root, *, reviewed=True):
    directory = root/"qualification"
    directory.mkdir()
    attempts, evidence = [], {}
    for state in (12, 0):
        folder = directory/f"reference-{state:03d}"
        folder.mkdir()
        for view in ("main", "wrist"):
            data = f"fixture video {state} {view}".encode()
            (folder/f"{view}.mp4").write_bytes(data)
            evidence[f"{folder.name}/{view}.mp4"] = hashlib.sha256(data).hexdigest()
        attempts.append({"path": folder.name, "state_id": state, "seed": 1729+state, "status": "completed",
                         "result": {"backend": "libero", "outcome": "success", "steps": 128}})
    report = {"protocol": "qualification-v1", "schema_version": "1.0", "qualified": True,
              "scene_review_approved": reviewed, "state_ids": [12, 0], "attempts": attempts,
              "scene_review": {"evidence_hash": json_hash(evidence)}, "evidence_sha256": evidence,
              "environment": {"private_path": "/operator/private-models"}}
    (directory/"qualification.json").write_text(json.dumps(report))
    return directory, report


def test_authenticated_previews_use_completed_references_and_verify_requested_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILUREFORGE_API_TOKEN", "test-local-token")
    directory, report = fixture(tmp_path)
    base = "/api/qualification/references"
    auth = {"Authorization": "Bearer test-local-token"}
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(base).status_code == 401
        metadata = client.get(base, headers=auth)
        assert metadata.status_code == 200
        refs = metadata.json()["references"]
        assert [r["state_id"] for r in refs] == [0, 12]
        assert set(refs[0]["cameras"]) == {"main", "wrist"}
        uri = refs[0]["cameras"]["main"]
        assert client.get(uri).status_code == 401
        response = client.get(uri, headers=auth)
        assert response.content == b"fixture video 0 main" and response.headers["content-type"] == "video/mp4"
        partial = client.get(uri, headers={**auth, "Range": "bytes=2-7"})
        assert partial.status_code == 206 and partial.content == response.content[2:8]
        assert partial.headers["content-range"] == f"bytes 2-7/{len(response.content)}"
        assert client.get(uri, headers={**auth, "Range": "bytes=200-"}).status_code == 416
        for url in ("/api/health", "/api/catalog", base):
            assert "/operator/private-models" not in client.get(url, headers=auth).text
        (directory/"reference-000"/"main.mp4").write_bytes(b"changed")
        assert client.get(uri, headers={**auth, "Range": "bytes=0-2"}).status_code == 409
        assert client.get(base+"/0/qualification.json", headers=auth).status_code == 422
        assert client.get(base+"/999/main", headers=auth).status_code == 404
        # Replacing a recorded digest alone invalidates the original operator attestation.
        report["evidence_sha256"]["reference-000/main.mp4"] = hashlib.sha256(b"changed").hexdigest()
        (directory/"qualification.json").write_text(json.dumps(report))
        assert client.get(uri, headers=auth).status_code == 409


def test_private_pending_and_unlisted_paths_have_no_preview(tmp_path):
    directory, report = fixture(tmp_path, reviewed=False)
    base = "/api/qualification/references"
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(base).json() == {"references": []}
        assert client.get(base+"/0/main").status_code == 404
        report["scene_review_approved"] = True
        report["attempts"][0]["path"] = "../private-staging"
        report["attempts"][1]["status"] = "running"
        (directory/"qualification.json").write_text(json.dumps(report))
        assert client.get(base).json() == {"references": []}
        assert client.get(base+"/12/main").status_code == 404
        report["attempts"][1]["status"] = "completed"
        del report["evidence_sha256"]["reference-000/wrist.mp4"]
        report["scene_review"]["evidence_hash"] = json_hash(report["evidence_sha256"])
        (directory/"qualification.json").write_text(json.dumps(report))
        assert client.get(base).json() == {"references": []}
