import hashlib
import json
import shutil
import subprocess
import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from failureforge.contracts import config_hash
from failureforge.project_camera import CameraReplays, _surfaces, camera_router


def test_mesh_references_are_bound_to_the_snapshot(tmp_path):
    uri = "package://device/links/foot.stl"
    model = ('<robot><mesh filename="'+uri+'"/></robot>').encode()
    asset = {"id":"asset_"+"1"*32, "kind":"cad","filename":"foot.stl","project_id":"p",
             "sha256":hashlib.sha256(b"surface").hexdigest()}
    (tmp_path/(asset["id"]+".blob")).write_bytes(b"surface")
    assert _surfaces(model,{"project_id":"p"},[asset],tmp_path) == {uri:b"surface"}
    assert _surfaces(model,{"project_id":"p"},[asset,asset],tmp_path) == {}
    with pytest.raises(ValueError,match="different project"):
        _surfaces(model,{"project_id":"other"},[asset],tmp_path)
    with pytest.raises(ValueError,match="differs"):
        _surfaces(model,{"project_id":"p"},[{**asset,"sha256":"changed"}],tmp_path)


@pytest.mark.parametrize("compared", [False, True])
def test_two_encoded_views_from_new_field(tmp_path, compared):
    if not sys.platform.startswith("linux") or not all(shutil.which(cmd) for cmd in ("ffmpeg","ffprobe")):
        pytest.skip("Requires the Linux camera worker with FFmpeg")
    pytest.importorskip("mujoco")
    from types import SimpleNamespace

    parts = {"snapshot":{"assets":[]}, "adapter":"thermal_rod","runtime":{}, "inputs":{"area_m2":.0006},
             "result":{"traces":{"node_position_m":[0,.012,.061,.09],"temperature_k":[297.,305.,311.,298.]}}}
    record = {**parts,"id":"new","project_id":"fixture","status":"completed","evidence_hash":config_hash(parts)}
    other_parts = {**parts,"result":{"traces":{"node_position_m":[0,.09],"temperature_k":[305.,323.]}}}
    other = {**record,**other_parts,"id":"warmer","evidence_hash":config_hash(other_parts)}
    def get(project, run):
        if (project,run) == ("fixture","warmer"):
            return other
        if (project,run) != ("fixture","new"):
            from fastapi import HTTPException
            raise HTTPException(404)
        return record
    jobs = CameraReplays(SimpleNamespace(get=get, projects=SimpleNamespace(root=tmp_path)), tmp_path/"cameras")
    app = FastAPI()
    app.include_router(camera_router(jobs))
    client = TestClient(app)
    path = "/api/projects/fixture/analysis/new/camera-replay"
    if compared:
        path += "/with/warmer"
    try:
        assert client.get(path).json()["status"] == "available"
        assert client.post(path).json()["status"] == "rendering"
        assert client.post(path).json()["status"] in ("rendering","ready")
        deadline = time.monotonic()+70
        while time.monotonic() < deadline:
            response = client.get(path).json()
            if response["status"] != "rendering":
                break
            time.sleep(.2)
        assert response["status"] == "ready", response
        assert len(response["views"]) == 2
        assert response["frame_count"] >= 2
        assert ("323 K" if compared else "311 K") in response["description"]
        assert "camera_comparison_scale" not in record
        assert client.get("/api/projects/fixture/analysis/new/camera-replay/with/missing").status_code == 404
        signatures = []
        for view in response["views"]:
            assert view["url"] == f"{path}/{view['id']}.mp4"
            ranged = client.get(view["url"],headers={"Range":"bytes=0-31"})
            assert ranged.status_code == 206 and len(ranged.content) == 32
            assert client.get(view["url"].replace("fixture","other")).status_code == 404
            _, key = jobs._source("fixture","new","warmer" if compared else None)
            assert (key != record["evidence_hash"]) is compared
            file = jobs.root/key/(view["id"]+".mp4")
            probe = json.loads(subprocess.check_output(["ffprobe","-v","error","-show_streams","-of","json",str(file)]))
            stream = probe["streams"][0]
            assert (stream["width"],stream["height"],stream["codec_name"]) == (640,360,"h264")
            assert float(stream["duration"]) == pytest.approx(response["duration_s"],abs=.002)
            signatures.append(hashlib.sha256(file.read_bytes()).hexdigest())
        assert signatures[0] != signatures[1]
    finally:
        jobs.pool.shutdown()


def test_uploaded_robot_with_its_own_camera_through_normal_project_workflow(tmp_path):
    if not sys.platform.startswith("linux") or not shutil.which("ffmpeg"):
        pytest.skip("Requires the Linux camera worker with FFmpeg")
    pytest.importorskip("mujoco")
    from failureforge.api import create_app

    model = b"""<robot name="inspection slide">
      <link name="base"><visual><geometry><box size=".19 .06 .04"/></geometry></visual></link>
      <link name="stage"><visual><geometry><mesh filename="package://fixture/saddle.stl"/></geometry></visual></link>
      <joint name="feed" type="prismatic"><parent link="base"/><child link="stage"/>
        <origin xyz="0 0 .03"/><axis xyz="0 1 0"/><limit lower="-.05" upper=".05" velocity=".5"/></joint>
      <gazebo reference="stage"><sensor type="camera" name="Feed inspection">
        <pose>-.15 .02 .1 0 .58 0</pose><camera><horizontal_fov>1.2</horizontal_fov>
        <image><width>320</width><height>240</height></image></camera></sensor></gazebo></robot>"""
    surface = b"""solid saddle
facet normal 0 0 1
outer loop
vertex 0 0 0
vertex .05 0 .03
vertex 0 .025 .01
endloop
endfacet
endsolid saddle
"""
    with TestClient(create_app(tmp_path)) as client:
        project = client.post("/api/projects",json={"name":"Inspection slide","entry_stage":"model",
                              "analysis_type":"robot_behavior","goal":"Move the inspection stage",
                              "success_criteria":"Reach the feed target"}).json()
        path = "/api/projects/"+project["id"]
        for name,kind,data in (("fixture.urdf","robot_model",model),("saddle.stl","cad",surface)):
            uploaded = client.post(path+"/assets",params={"filename":name,"kind":kind},content=data)
            assert uploaded.is_success, uploaded.text
            project = uploaded.json()
        identifier = next(a["id"] for a in project["assets"] if a["kind"] == "robot_model")
        receipt = client.post(path+"/analysis",json={"adapter":"robot_motion","label":"Travel",
                  "expected_revision":project["revision"],"inputs":{"model_asset_id":identifier,
                  "targets":{"feed":.033},"duration_s":1,"samples":25}})
        assert receipt.is_success, receipt.text
        run = path+"/analysis/"+receipt.json()["id"]
        def wait_for(url, waiting):
            deadline = time.monotonic()+60
            while time.monotonic() < deadline:
                value = client.get(url).json()
                if value["status"] not in waiting:
                    return value
                time.sleep(.15)
            pytest.fail("Timed out waiting for "+url)
        solved = wait_for(run,{"queued","running"})
        assert solved["status"] == "completed",solved.get("error")
        url = run+"/camera-replay"
        assert client.post(url).json()["status"] == "rendering"
        cameras = wait_for(url,{"rendering"})
        assert cameras["status"] == "ready",cameras
        assert [v["label"] for v in cameras["views"]] == ["Workcell overview","Feed inspection (rendered)"]
        assert "Frame guides" not in cameras["description"]
        for view in cameras["views"]:
            media = client.get(view["url"])
            assert media.headers["Content-Type"] == "video/mp4"
            assert len(media.content) > 1024
