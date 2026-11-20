"""Camera replay jobs are derived artifacts. The original solver evidence stays immutable."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .project_bundle import ASSET_ID, evidence


class View(BaseModel):
    id: Literal["main", "detail"]
    label: str
    url: str


class Replay(BaseModel):
    status: Literal["available", "rendering", "ready", "unavailable", "failed"]
    description: str
    views: list[View] | None = None
    duration_s: float | None = None
    frame_count: int | None = None


def _source_asset(asset_root, run, asset):
    identifier = asset["id"]
    if not ASSET_ID.fullmatch(identifier) or asset["project_id"] != run["project_id"]:
        raise ValueError("Model asset belongs to a different project revision")
    data = (asset_root/(identifier+".blob")).read_bytes()
    if hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise ValueError("Model asset differs from its run snapshot")
    return data


def _surfaces(model, run, assets, asset_root):
    # References are identifiers. Only read local files from a verified revision or model pack.
    references = {n.get("filename") for n in ET.fromstring(model).iter("mesh") if n.get("filename")}
    names = Counter(PurePosixPath(ref).name for ref in references)
    pack = Path(__file__).with_name("visual_models") / hashlib.sha256(model).hexdigest()
    manifest = pack / "manifest.json"
    packaged = json.loads(manifest.read_text(encoding="utf-8-sig"))["meshes"] if manifest.is_file() else {}
    meshes, total_bytes = {}, 0
    for ref in sorted(references):
        name = PurePosixPath(ref).name
        if not name.lower().endswith(".stl"):
            continue
        matches = [asset for asset in assets if asset["kind"] == "cad" and asset["filename"] == name]
        if len(matches) == 1 and names[name] == 1:
            try:
                data = _source_asset(asset_root,run,matches[0])
            except FileNotFoundError:
                continue
        elif ref in packaged and not matches:
            entry = packaged[ref]
            if entry["filename"] != name or Path(name).name != name:
                raise ValueError("Invalid visual model pack")
            data = (pack/name).read_bytes()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("Visual mesh differs from the installed pack manifest")
        else:
            continue
        total_bytes += len(data)
        if total_bytes > 96*1024**2:
            raise ValueError("Model exceeds the 96 MiB camera mesh allowance")
        meshes[ref] = data
    return meshes


def build_scene(run, asset_root):
    assets = run["snapshot"]["assets"]
    by_id = {asset["id"]:asset for asset in assets}
    inputs = run["inputs"]
    if run["adapter"] in ("robot_motion", "packaging_lift", "packaging_lift_timed_v2"):
        from .project_camera_motion import motion_scene
    if run["adapter"] == "robot_motion":
        identifier = inputs.get("model_asset_id")
        model = None
        meshes = {}
        if identifier:
            metadata = run["result"]["model"]
            if identifier != metadata.get("asset_id"):
                raise ValueError("Saved trajectory identifies a different model")
            if identifier not in by_id:
                return motion_scene(run)
            try:
                model = _source_asset(asset_root,run,by_id[identifier])
            except FileNotFoundError:
                return motion_scene(run)
            if hashlib.sha256(model).hexdigest() != metadata["urdf_sha256"]:
                raise ValueError("Uploaded URDF differs from the trajectory source")
            meshes = _surfaces(model,run,assets,asset_root)
        return motion_scene(run,model,meshes)
    if run["adapter"] in ("packaging_lift", "packaging_lift_timed_v2"):
        return motion_scene(run)
    from .project_camera_fields import field_scene
    identifier = inputs.get("cad_asset_id") if run["adapter"] == "cad_inventory" else None
    model = None
    if identifier in by_id:
        try:
            model = _source_asset(asset_root,run,by_id[identifier])
        except FileNotFoundError:
            pass  # The checksum-protected result also contains the archived CAD preview.
    return field_scene(run,model)


def _render_job(asset_root, output):
    run = json.load(sys.stdin)
    evidence(run)
    scene = build_scene(run,asset_root)
    if scene is None:
        result = {"status":"unavailable","description":"This record lacks geometry or samples needed for a camera view."}
    else:
        from .camera_render import render
        result = {"status":"ready", **render(scene,output)}
    (output/"manifest.json").write_text(json.dumps(result),encoding="utf-8")


class CameraReplays:
    def __init__(self, runs, root):
        self.runs = runs
        source = Path(__file__).parent
        revision = hashlib.sha256()
        for filename in ("camera_render.py","camera_mesh.py","camera_scene.py","project_camera.py",
                         "project_camera_fields.py","project_camera_motion.py","project_replay.py"):
            revision.update((source/filename).read_bytes())
        for manifest in sorted((source/"visual_models").glob("*/manifest.json")):
            revision.update(manifest.read_bytes())
        self.root = root / revision.hexdigest()[:20]
        self.pool = ThreadPoolExecutor(max_workers=2,thread_name_prefix="project-camera")
        self.lock = threading.Lock()
        self.pending = set()
        self.errors = {}

    def _publish(self, record, key):
        try:
            self.root.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.root,prefix=".render-") as directory:
                staging = Path(directory)/"pair"
                staging.mkdir()
                env = {**os.environ,"PYTHONPATH":str(Path(__file__).resolve().parents[1]),
                       "OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"1","LP_NUM_THREADS":"3"}
                if sys.platform.startswith("linux"):
                    env.setdefault("MUJOCO_GL","egl")
                outcome = subprocess.run([sys.executable,"-m","failureforge.project_camera",
                                          str(self.runs.projects.root),str(staging)], env=env,
                                         input=json.dumps(record),capture_output=True,text=True,timeout=240)
                if outcome.returncode:
                    logging.getLogger(__name__).error("Camera worker for %s: %s",record["id"],outcome.stderr[-3000:])
                    raise RuntimeError("The camera renderer could not complete this recording.")
                try:
                    staging.rename(self.root/key)
                except OSError:
                    if not (self.root/key/"manifest.json").is_file():
                        raise
        except Exception as error:
            logging.getLogger(__name__).exception("Camera job failed for %s",record["id"])
            with self.lock:
                if len(self.errors) >= 128:
                    self.errors.pop(next(iter(self.errors)))
                self.errors[key] = str(error) if type(error) is RuntimeError else "The camera worker could not finish. Retry the rendering."
        finally:
            with self.lock:
                self.pending.discard(key)

    def _source(self, project, run, other):
        record = self.runs.get(project,run)
        if record["status"] != "completed":
            return record, None
        evidence(record)
        key = record["evidence_hash"]
        if other is not None:
            from .project_camera_fields import comparison_scale
            peer = self.runs.get(project,other)
            if peer["status"] != "completed":
                return record, None
            evidence(peer)
            scale = comparison_scale(record, peer)
            if scale is None:
                return record, None
            record = {**record, "camera_comparison_scale":scale}
            key = hashlib.sha256((key+json.dumps(scale,sort_keys=True)).encode()).hexdigest()
        return record, key

    def describe(self, project, run, enqueue=False, other=None):
        record, key = self._source(project,run,other)
        if key is None:
            return {"status":"unavailable","description":"Camera playback requires compatible completed run evidence."}
        manifest = self.root/key/"manifest.json"
        if manifest.is_file():
            info = json.loads(manifest.read_text(encoding="utf-8"))
            if info["status"] == "ready":
                base = f"/api/projects/{project}/analysis/{run}/camera-replay"
                if other is not None:
                    base += f"/with/{other}"
                info["views"] = [{"id":name,"label":label,"url":f"{base}/{name}.mp4"}
                                 for name,label in zip(("main","detail"),info.pop("labels"),strict=True)]
            return info
        if not shutil.which("ffmpeg") or not importlib.util.find_spec("mujoco"):
            return {"status":"unavailable","description":"This installation needs the project-robot extra and FFmpeg for 3D camera playback."}
        with self.lock:
            if key in self.pending:
                return {"status":"rendering","description":"Rendering both cameras from the saved run."}
            if not enqueue:
                if key in self.errors:
                    return {"status":"failed","description":self.errors[key]}
                return {"status":"available","description":"The saved run can be inspected by the camera renderer."}
            if len(self.pending) >= 16:
                raise HTTPException(429,"The render queue is full. Retry shortly.",headers={"Retry-After":"5"})
            self.errors.pop(key,None)
            self.pending.add(key)
            self.pool.submit(self._publish,record,key)
            return {"status":"rendering","description":"Rendering both cameras from the saved run."}

    def video(self, project, run, view, other=None):
        _, key = self._source(project,run,other)
        if key is None:
            raise HTTPException(404,"Camera video is unavailable")
        path = self.root/key/(view+".mp4")
        if not path.is_file():
            raise HTTPException(404,"Camera video is unavailable")
        return FileResponse(path,media_type="video/mp4",headers={"Cache-Control":"private, no-cache"})


def camera_router(cameras):
    router = APIRouter(prefix="/api/projects/{project}/analysis/{run}/camera-replay",tags=["project replay"])

    @router.get("",response_model=Replay,response_model_exclude_none=True)
    def describe(project: str, run: str):
        return cameras.describe(project,run)

    @router.post("",response_model=Replay,response_model_exclude_none=True)
    def prepare(project: str, run: str):
        return cameras.describe(project,run,enqueue=True)

    @router.get("/{view}.mp4",response_class=FileResponse,responses={200:{"content":{"video/mp4":{}}}})
    def video(project: str, run: str, view: Literal["main","detail"]):
        return cameras.video(project,run,view)

    @router.get("/with/{other}",response_model=Replay,response_model_exclude_none=True)
    def describe_comparison(project: str, run: str, other: str):
        return cameras.describe(project,run,other=other)

    @router.post("/with/{other}",response_model=Replay,response_model_exclude_none=True)
    def prepare_comparison(project: str, run: str, other: str):
        return cameras.describe(project,run,enqueue=True,other=other)

    @router.get("/with/{other}/{view}.mp4",response_class=FileResponse,responses={200:{"content":{"video/mp4":{}}}})
    def comparison_video(project: str, run: str, other: str, view: Literal["main","detail"]):
        return cameras.video(project,run,view,other=other)

    return router


if __name__ == "__main__":
    _render_job(Path(sys.argv[1]),Path(sys.argv[2]))
