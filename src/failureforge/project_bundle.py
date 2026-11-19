"""Portable evidence and inputs for one project analysis; offline inspection and rerun."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

from .artifacts import ArtifactError
from .contracts import canonical_json, config_hash
from .project_solver import ASSET_FIELDS, MODELS
from .projects import ASSET_LIMIT

FORMAT = "failureforge.project-analysis.v1"
MAX_RECORD = 16 * 1024**2
ASSET_ID = re.compile(r"asset_[0-9a-f]{32}")


def require(value, message):
    if not value:
        raise ArtifactError(message)


def evidence(run):
    parts = {k: run[k] for k in ("snapshot", "inputs", "adapter", "runtime", "result")}
    if run.get("binding_evidence"):
        parts.update(definition=run["definition"], binding_evidence=run["binding_evidence"])
    require(config_hash(parts) == run["evidence_hash"], "Project run evidence checksum differs")


def resources(run):
    require(run["adapter"] in MODELS, "Unsupported project adapter")
    records = {a["id"]: a for a in run["snapshot"]["assets"]}
    needed = set()
    for field, (kind, suffix) in ASSET_FIELDS.items():
        identifier = run["inputs"].get(field)
        if identifier is None:
            continue
        asset = records.get(identifier)
        require(asset and asset["kind"] == kind and Path(asset["filename"]).suffix.lower() == suffix,
                f"Missing input asset for {field}")
        needed.add(identifier)
    for asset in records.values():
        name = asset["filename"].lower()
        if asset["kind"] == "requirements" and (name == "provenance.json" or
                (name.startswith(("license", "notice")) and name.endswith((".md", ".txt")))):
            needed.add(asset["id"])
    for identifier in needed:
        require(ASSET_ID.fullmatch(identifier), "Invalid project resource identity")
    return {k: records[k] for k in sorted(needed)}


def export_run(runs, project_id, run_id):
    run = runs.get(project_id, run_id)
    require(run["status"] == "completed", "Only completed project measurements have exportable evidence")
    evidence(run)
    stream = io.BytesIO()
    manifest = {"format": FORMAT, "run_id": run_id, "files": {}}
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as output:
        def write(name, content):
            output.writestr(name, content)
            manifest["files"][name] = hashlib.sha256(content).hexdigest()
        data = canonical_json(run).encode()
        require(len(data) <= MAX_RECORD, "Result exceeds the portable record allowance")
        assets = resources(run)
        require(sum(a["size_bytes"] for a in assets.values()) + len(data) + 32768 <= 64*1024**2,
                "Referenced files exceed the portable bundle allowance")
        write("run.json", data)
        for identifier, asset in assets.items():
            _, path = runs.projects.asset(project_id, identifier)
            data = path.read_bytes()
            require(hashlib.sha256(data).hexdigest() == asset["sha256"], "Input changed after the run")
            write("assets/" + identifier, data)
        output.writestr("manifest.json", canonical_json(manifest))
    return stream.getvalue()


def inspect_project_bundle(path, *, rerun=False):
    try:
        with zipfile.ZipFile(path) as z:
            items = z.infolist()
            names = {i.filename for i in items}
            require(2 <= len(items) <= 42 and len(items) == len(names), "Invalid project bundle inventory")
            for i in items:
                maximum = MAX_RECORD if i.filename == "run.json" else 32768 if i.filename == "manifest.json" else ASSET_LIMIT
                require(i.file_size <= maximum, "Project bundle member exceeds its size limit")
            require(sum(i.file_size for i in items) <= 64*1024**2, "Project bundle exceeds 64 MiB")
            manifest = json.loads(z.read("manifest.json"))
            require(manifest["format"] == FORMAT and names == set(manifest["files"]) | {"manifest.json"},
                    "Invalid project bundle manifest")
            run = json.loads(z.read("run.json"))
            require(run["id"] == manifest["run_id"] and run["status"] == "completed", "Invalid run identity")
            evidence(run)
            assets = resources(run)
            require(names == {"manifest.json", "run.json"} | {"assets/"+k for k in assets},
                    "Unexpected or missing project bundle member")
            payloads = {}
            for name, expected in manifest["files"].items():
                content = z.read(name)
                require(hashlib.sha256(content).hexdigest() == expected, "Project bundle file checksum differs")
                if name.startswith("assets/"):
                    identifier = name.split("/")[1]
                    require(expected == assets[identifier]["sha256"], "Resource differs from execution snapshot")
                    payloads[identifier] = content
    except (zipfile.BadZipFile, KeyError, AttributeError, TypeError, UnicodeError, RecursionError) as exc:
        raise ArtifactError("Invalid project analysis archive") from exc
    report = {"verified": True, "format": FORMAT, "id": run["id"], "evidence_hash": run["evidence_hash"],
              "project_revision": run["project_revision"], "adapter": run["adapter"], "files": len(names),
              "resources": [a["filename"] for a in assets.values()]}
    if rerun:
        with tempfile.TemporaryDirectory(prefix="failureforge-project-bundle-") as temp:
            root = Path(temp)
            known = {}
            for identifier, content in payloads.items():
                local = root / identifier
                local.write_bytes(content)
                known[identifier] = {**assets[identifier], "path": str(local)}
            job = {"adapter": run["adapter"], "analysis_type": run["snapshot"]["analysis_type"],
                   "inputs": run["inputs"], "assets": known}
            result_path = root/"output.json"
            env = {**os.environ, "FAILUREFORGE_SOLVER_OUTPUT": str(result_path),
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
            try:
                subprocess.run([sys.executable, "-m", "failureforge.project_solver"], cwd=root,
                               input=canonical_json(job).encode(), env=env, timeout=75, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.SubprocessError as exc:
                raise ArtifactError("Fresh project solver execution did not finish successfully") from exc
            replay = json.loads(result_path.read_text(encoding="utf-8"))
            require(replay["status"] == "completed", replay.get("error", "Fresh solver execution failed"))
            measured = replay["result"]
            report["rerun"] = {"same_runtime_identity": replay["runtime"] == run["runtime"],
                               "exact_result_match": config_hash(measured) == config_hash(run["result"]),
                               "passed": measured.get("passed"), "summary": measured.get("summary", measured.get("metrics"))}
    return report


def bundle_router(runs):
    router = APIRouter(tags=["project analyses"])
    @router.get("/api/projects/{project}/analysis/{run}/bundle", response_class=Response,
                responses={200: {"content": {"application/zip": {}}}})
    def download(project: str, run: str):
        data = export_run(runs, project, run)
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{run}.zip"'})
    return router
