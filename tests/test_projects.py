import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.projects import ASSET_LIMIT, INSPECTION_LIMIT


def specification(**changes):
    return {"name": "Hand investigation", "entry_stage": "concept", "analysis_type": "robot_behavior",
            "goal": "Rotate a cube", "success_criteria": "Rotate 90 degrees without dropping it",
            "robot_source": "custom", "notes": "", "parameters": [], "test_plans": [], **changes}


def create(client, **changes):
    response = client.post("/api/projects", json=specification(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, identifier, filename="hand.urdf", kind="robot_model", body=b'<robot name="hand"><link name="base"/></robot>'):
    return client.post(f"/api/projects/{identifier}/assets", params={"filename": filename, "kind": kind}, content=body,
                       headers={"Content-Type": "application/octet-stream"})


def test_project_roundtrip_is_durable_and_updates_are_fenced(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        original = create(client)
        assert original["revision"] == 1
        assert original["readiness"]["execution_allowed"] is False
        assert client.get("/api/projects").json()["items"][0] == original
        update = specification(name="Revised hand", expected_revision=1)
        changed = client.post(f"/api/projects/{original['id']}", json=update)
        assert changed.status_code == 200
        assert changed.json()["revision"] == 2
        assert client.post(f"/api/projects/{original['id']}", json=update).status_code == 409
        assert client.get("/api/projects/absent").status_code == 404
    with TestClient(create_app(tmp_path)) as client:
        restored = client.get(f"/api/projects/{original['id']}").json()
        assert restored == changed.json()
        assert client.get("/api/campaigns").json() == {"items": []}


@pytest.mark.parametrize("stage", ["concept", "cad", "model", "simulation", "prototype"])
@pytest.mark.parametrize("analysis", ["robot_behavior", "structural", "thermal"])
def test_all_entry_stages_and_analyses_have_honest_execution_gates(tmp_path, stage, analysis):
    with TestClient(create_app(tmp_path)) as client:
        project = create(client, entry_stage=stage, analysis_type=analysis)
        readiness = project["readiness"]
        assert readiness["execution_allowed"] is False
        assert next(c for c in readiness["checks"] if c["id"] == "execution_adapter")["status"] == "blocked"
        assert [p["id"] for p in readiness["phases"]] == ["concept", "preparation", "validation", "test_design", "qualification", "execution", "investigation", "regression"]


@pytest.mark.parametrize("change", [
    {"name": " "}, {"goal": ""}, {"entry_stage": "ready"}, {"analysis_type": "magic"},
    {"robot_source": "supported"}, {"robot_template": "leap_hand_v1"},
    {"execution_allowed": True}, {"readiness": {"execution_allowed": True}},
    {"parameters": [{"name": "mass", "value": 2, "source": "measured"}]},
    {"parameters": [{"name": "mass", "value": "2", "source": "verified"}]},
    {"parameters": [{"name": "mass", "value": "2", "source": "estimated", "range_min": 3, "range_max": 1}]},
    {"parameters": [{"name": "mass", "value": "2", "source": "estimated", "range_min": 1}]},
    {"parameters": [{"name": "mass", "value": "2", "source": "estimated", "range_min": False, "range_max": 3}]},
    {"parameters": [{"name": "Mass", "value": "2", "source": "estimated"}, {"name": "mass", "value": "3", "source": "estimated"}]},
    {"test_plans": [{"name": "test", "objective": "hold", "success_criteria": "no drop", "variation": "mass", "timeout_seconds": -1}]},
])
def test_invalid_intake_and_capability_spoofing_rejected(tmp_path, change):
    with TestClient(create_app(tmp_path)) as client:
        assert client.post("/api/projects", json=specification(**change)).status_code == 422


def test_nonfinite_parameter_and_excessive_lists_rejected(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        parameter = {"name": "mass", "value": "2", "source": "estimated", "range_min": float("nan"), "range_max": 3}
        response = client.post("/api/projects", content=json.dumps(specification(parameters=[parameter])), headers={"Content-Type": "application/json"})
        assert response.status_code == 422
        parameters = [{"name": f"p{i}", "value": "1", "source": "estimated"} for i in range(81)]
        assert client.post("/api/projects", json=specification(parameters=parameters)).status_code == 422
        plan = {"name": "t", "objective": "hold", "success_criteria": "no drop", "variation": "mass"}
        assert client.post("/api/projects", json=specification(test_plans=[dict(plan, name=f"t{i}") for i in range(31)])).status_code == 422


def test_asset_inspection_download_integrity_and_revision(tmp_path):
    body = b'<robot name="hand"><link name="base"><visual><geometry><mesh filename="package://hand/base.stl"/></geometry></visual></link><joint name="finger" type="fixed"/></robot>'
    app = create_app(tmp_path)
    with TestClient(app) as client:
        project = create(client)
        response = upload(client, project["id"], body=body)
        assert response.status_code == 201
        updated = response.json()
        assert updated["revision"] == 2
        asset = updated["assets"][0]
        assert asset["sha256"] == hashlib.sha256(body).hexdigest()
        assert asset["inspection"]["details"]["links"] == 1
        assert asset["inspection"]["details"]["missing_explicit_inertia"] == 1
        assert asset["inspection"]["details"]["unresolved_references"] == ["package://hand/base.stl"]
        assert updated["readiness"]["execution_allowed"] is False
        downloaded = client.get(asset["download_url"])
        assert downloaded.content == body
        assert "attachment" in downloaded.headers["content-disposition"]
        another = create(client)
        assert client.get(f"/api/projects/{another['id']}/assets/{asset['id']}").status_code == 404
        assert client.post(f"/api/projects/{project['id']}", json=specification(expected_revision=1)).status_code == 409
        path = app.state.projects.asset_path(asset["id"])
        path.write_bytes(b"corrupted")
        assert client.get(asset["download_url"]).status_code == 409


@pytest.mark.parametrize("filename,kind,body,status", [
    ("../outside.urdf", "robot_model", b"x", 422),
    ("C:\\outside.urdf", "robot_model", b"x", 422),
    ("CON.urdf", "robot_model", b"x", 422),
    ("page.html", "requirements", b"<script>bad</script>", 422),
    ("a.urdf", "robot_model", b"", 422),
    ("a.urdf", "robot_model", b'<!DOCTYPE robot [<!ENTITY x SYSTEM "file:///etc/passwd">]><robot>&x;</robot>', 422),
    ("a.urdf", "robot_model", "<robot/>".encode("utf-16"), 422),
    ("a.urdf", "robot_model", b"<robot>", 422),
    ("a.xml", "robot_model", b"<other/>", 422),
    ("a.json", "requirements", b'{"value":NaN}', 422),
    ("a.json", "requirements", b'{"value":1e999}', 422),
    ("a.json", "requirements", b"[" * 70 + b"0" + b"]" * 70, 422),
    ("a.xml", "robot_model", b"<robot>" + b"<x>" * 70 + b"</x>" * 70 + b"</robot>", 422),
    ("a.xml", "robot_model", b"<robot>" + b"<x/>" * 20001 + b"</robot>", 422),
    ("a.json", "requirements", b" " * (INSPECTION_LIMIT + 1), 413),
    ("a.txt", "requirements", b"x" * (ASSET_LIMIT + 1), 413),
], ids=["traversal", "absolute-path", "reserved-name", "extension", "empty", "entity", "encoding", "malformed", "wrong-root", "nan", "overflow", "json-depth", "xml-depth", "xml-count", "inspection-size", "upload-size"])
def test_upload_rejection_is_bounded_and_leaves_no_assets(tmp_path, filename, kind, body, status):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        project = create(client)
        response = upload(client, project["id"], filename, kind, body)
        assert response.status_code == status, response.text
        assert client.get(f"/api/projects/{project['id']}").json()["assets"] == []
        assert list((tmp_path / "project-assets").iterdir()) == []


def test_actual_byte_limits_apply_without_content_length(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project = create(client)
        chunks = (b"x" * (1024 * 1024) for _ in range(11))
        response = client.post(f"/api/projects/{project['id']}/assets", params={"filename": "notes.txt", "kind": "requirements"}, content=chunks)
        assert response.status_code == 413
        assert list((tmp_path / "project-assets").iterdir()) == []
        response = client.post("/api/projects", content=(b" " * 32768 for _ in range(3)))
        assert response.status_code == 413


def test_complete_intake_remains_blocked_and_export_preserves_evidence(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project = create(client, entry_stage="prototype", robot_source="supported", robot_template="leap_hand_v1",
                         parameters=[{"name": "mass", "value": "0.281", "unit": "kg", "source": "calibrated", "evidence": "bench log 2026-11-19", "range_min": 0.2, "range_max": 0.4}],
                         test_plans=[{"name": "Rotate", "objective": "Rotate cube", "success_criteria": "90 degrees without a drop", "variation": "Object mass", "timeout_seconds": 5}])
        assert upload(client, project["id"]).status_code == 201
        script = b'raise RuntimeError("NEVER EXECUTE UPLOADED CONTROLLERS")'
        result = upload(client, project["id"], "controller.py", "controller", script).json()
        assert result["readiness"]["phase"] == "qualification"
        assert result["readiness"]["execution_allowed"] is False
        assert next(c for c in result["readiness"]["checks"] if c["id"] == "model")["status"] == "review"
        assert result["assets"][-1]["inspection"]["status"] == "stored"
        report = client.get(f"/api/projects/{project['id']}/export")
        assert report.status_code == 200
        assert "attachment" in report.headers["content-disposition"]
        assert report.json()["report_type"] == "preparation_report"
        assert report.json()["contains_simulation_results"] is False
        assert report.json()["project"] == result
        assert client.get("/api/campaigns").json() == {"items": []}
        catalog = client.get("/api/projects/catalog").json()
        assert catalog["limits"]["asset_bytes"] == ASSET_LIMIT
        assert [t["id"] for t in catalog["robot_templates"] if t["execution_available"]] == ["two_finger_hand_v1"]


def test_measured_claim_without_evidence_does_not_complete_evidence_check(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project = create(client, entry_stage="prototype", parameters=[{"name": "mass", "value": "1", "source": "measured"}])
        checks = {check["id"]: check for check in project["readiness"]["checks"]}
        assert checks["measurements"]["status"] == "missing"
        assert checks["parameter_evidence"]["status"] == "missing"


def test_mjcf_and_json_inspection_never_claim_model_compilation(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project = create(client)
        response = upload(client, project["id"], "hand.xml", "robot_model", b'<mujoco><worldbody><body name="hand"><joint/><geom type="sphere" size="1"/></body></worldbody></mujoco>')
        inspection = response.json()["assets"][0]["inspection"]
        assert inspection["details"]["bodies"] == 1
        assert inspection["details"]["missing_explicit_inertia"] == 1
        response = upload(client, project["id"], "measurements.json", "measurements", b'{"mass":0.2}')
        asset = next(asset for asset in response.json()["assets"] if asset["filename"] == "measurements.json")
        assert asset["inspection"]["status"] == "inspected"
        assert "No domain schema" in asset["inspection"]["summary"]


def test_asset_capacity_and_duplicate_names_have_independent_identity(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        project = create(client)
        for index in range(40):
            response = upload(client, project["id"], "note.txt", "requirements", f"Requirement {index}".encode())
            assert response.status_code == 201
        assets = response.json()["assets"]
        assert len({asset["id"] for asset in assets}) == 40
        assert len({asset["sha256"] for asset in assets}) == 40
        assert upload(client, project["id"], "extra.txt", "requirements", b"Extra").status_code == 409
        assert len(list((tmp_path / "project-assets").iterdir())) == 40
    with TestClient(create_app(tmp_path)) as client:
        restored = client.get(f"/api/projects/{project['id']}").json()
        assert restored["assets"] == assets
        assert client.get(assets[0]["download_url"]).status_code == 200


@pytest.mark.parametrize("extension", ["png", "jpg", "jpeg", "webp"])
def test_concept_images_are_opaque_attachments_with_verified_downloads(tmp_path, extension):
    body = b"\x89PNG\r\n\x1a\nOpaque image fixture; no decoding or model inference"
    with TestClient(create_app(tmp_path)) as client:
        project = create(client)
        response = upload(client, project["id"], f"concept.{extension}", "requirements", body)
        assert response.status_code == 201
        asset = response.json()["assets"][0]
        assert asset["inspection"]["status"] == "stored"
        assert asset["inspection"]["details"] == {}
        assert asset["sha256"] == hashlib.sha256(body).hexdigest()
        downloaded = client.get(asset["download_url"])
        assert downloaded.status_code == 200
        assert downloaded.content == body
        assert downloaded.headers["content-type"] == "application/octet-stream"
        assert response.json()["readiness"]["execution_allowed"] is False
