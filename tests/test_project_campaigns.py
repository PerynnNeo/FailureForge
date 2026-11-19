import numpy as np
import pytest
from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.project_robot import HAND_URDF, RobotRunRequest, run_robot
from failureforge.project_replay import link_trajectories


def test_campaign_membership_pagination_and_legacy_groups(tmp_path):
    app = create_app(tmp_path)
    # Use the API without its worker lifespan so the queue remains deterministic.
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Test fixture", "entry_stage": "concept",
                          "analysis_type": "thermal", "goal": "Measure peak temperature",
                          "success_criteria": "Peak below 315 K"}).json()["id"]
    path = "/api/projects/" + project
    case = {"adapter": "thermal_rod", "label": "Boundary check", "inputs": {}}
    single = client.post(path + "/analysis", json={"expected_revision": 1, **case}).json()
    named = client.post(path + "/analysis-suite", json={"expected_revision": 1, "label": "First batch", "tests": [case]}).json()
    legacy = client.post(path + "/analysis-suite", json={"expected_revision": 1, "tests": [case, case]}).json()
    with app.state.store.connection(True) as db:
        db.execute("DELETE FROM project_named_suites WHERE suite_id=?", (legacy["suite_id"],))
    history = client.get("/api/project-campaigns").json()
    assert {row["suite_id"] for row in history["items"]} == {named["suite_id"], legacy["suite_id"]}
    assert history["total"] == 2
    assert len(client.get("/api/project-campaigns?offset=1&limit=1").json()["items"]) == 1
    result = client.get(f"/api/project-campaigns/{project}/{named['suite_id']}").json()
    assert (result["label"], result["status"], result["total"]) == ("First batch", "running", 1)
    assert result["runs"][0]["passed"] is None
    for owner, identifier in (("other", named["suite_id"]), (project, single["suite_id"])):
        assert client.get(f"/api/project-campaigns/{owner}/{identifier}").status_code == 404


def test_replay_reconstructs_both_branches_from_recorded_joint_positions():
    result = run_robot(RobotRunRequest(targets={"left_knuckle": -.3, "right_knuckle": .3}))
    data = link_trajectories(result, HAND_URDF)
    links = {item["name"]: item for item in data["links"]}
    assert data["time_s"] == result["trajectory"]["time_s"]
    assert links["right_tip"]["parent"] == "right_finger"
    assert np.allclose(links["left_tip"]["xyz_m"], result["trajectory"]["tip_xyz_m"])
    assert links["right_tip"]["xyz_m"][0] != links["right_tip"]["xyz_m"][-1]
    with pytest.raises(ValueError, match="differs"):
        link_trajectories(result, HAND_URDF + b" ")
