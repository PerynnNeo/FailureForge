"""HTTP boundary. GPU work is only executed by the separate worker."""
from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .artifacts import ArtifactError, ArtifactStore
from .contracts import CampaignSpec, RerunRequest, catalog
from .persistence import Conflict, Store


def public_data(value):
    """Keep worker fencing tokens and internal artifact directories off HTTP DTOs."""
    if isinstance(value, dict):
        return {key: public_data(item) for key, item in value.items() if key not in {"lease_token", "relative_dir"}}
    if isinstance(value, list):
        return [public_data(item) for item in value]
    return value


def create_app(data_dir: str | Path | None = None, web_dir: str | Path | None = None) -> FastAPI:
    root = Path(data_dir or os.environ.get("FAILUREFORGE_DATA_DIR", "data")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root / "failureforge.sqlite3")
    artifacts = ArtifactStore(root / "artifacts")
    app = FastAPI(title="FailureForge", version="0.1.0")
    app.state.store, app.state.artifacts, app.state.data_dir = store, artifacts, root
    token = os.environ.get("FAILUREFORGE_API_TOKEN")
    origins = os.environ.get("FAILUREFORGE_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000").split(",")
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key", "Authorization"])

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if request.url.path.startswith("/api"):
            preflight = (request.method == "OPTIONS" and request.headers.get("origin") in origins and
                         request.headers.get("access-control-request-method") in {"GET", "POST"})
            if token and not preflight and not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                if origin and origin not in origins:
                    return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
                try:
                    if int(request.headers.get("content-length", "0")) > 65536:
                        return JSONResponse({"detail": "Request body exceeds limit"}, status_code=413)
                except ValueError:
                    return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "Record not found"}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ArtifactError)
    async def invalid_artifact(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic error input may itself contain NaN; never echo it into JSON.
        return JSONResponse({"detail": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]}, status_code=422)

    def idempotency(key):
        if not key or not 8 <= len(key) <= 200:
            raise HTTPException(422, "Supply an Idempotency-Key of 8 to 200 characters")
        return key

    def readiness():
        path = root / "qualification" / "qualification.json"
        if not path.exists():
            return {"qualified": False, "reason": "Run qualification and review the policy camera frames on the RTX 5090 execution host."}
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            ready = bool(report.get("qualified") and report.get("scene_review_approved"))
            return {"qualified": ready, "reason": "Qualification recorded; worker rechecks runtime identity before execution." if ready else "Qualification or manual scene review is pending.", "report": report}
        except (ValueError, OSError):
            return {"qualified": False, "reason": "Qualification report is unreadable."}

    @app.get("/api/health")
    def health():
        store.recover_expired()
        worker = store.worker_status()
        return {"status": "ok", "runtime_mode": worker["backend"] if worker["online"] else "offline", "worker": worker,
                "readiness": readiness(), "sqlite": {"journal_mode": store.journal_mode}, "version": "0.1.0"}

    @app.get("/api/catalog")
    def get_catalog():
        return dict(catalog(), qualification=readiness())

    @app.get("/api/campaigns")
    def list_campaigns():
        return public_data({"items": store.list_campaigns()})

    def live_gate(backend):
        if backend == "libero":
            if not readiness()["qualified"]:
                raise HTTPException(409, "Robot execution requires successful qualification and scene review on the execution host")
            if not store.worker_status("libero")["online"]:
                raise HTTPException(409, "Robot worker is offline; existing evidence remains available")

    @app.post("/api/campaigns", status_code=202)
    def create_campaign(spec: CampaignSpec, idempotency_key: str | None = Header(None)):
        live_gate(spec.backend)
        return store.create_campaign(spec, idempotency(idempotency_key))

    @app.get("/api/campaigns/{identifier}")
    def get_campaign(identifier: str):
        return public_data(store.get_campaign(identifier))

    @app.get("/api/jobs/{identifier}")
    def get_job(identifier: str):
        job = store.get_job(identifier)
        # Only the worker process needs a claim token.
        return public_data(job)

    @app.post("/api/jobs/{identifier}/cancel")
    def cancel_job(identifier: str):
        store.request_cancel(identifier)
        return get_job(identifier)

    @app.post("/api/jobs/{identifier}/resume", status_code=202)
    def resume_job(identifier: str):
        job = store.get_job(identifier)
        live_gate(store.get_campaign(job["campaign_id"])["backend"])
        store.resume_job(identifier)
        return get_job(identifier)

    @app.get("/api/cases/{identifier}")
    def get_case(identifier: str):
        case = store.get_case(identifier)
        with store.connection() as db:
            case["jobs"] = [dict(row) for row in db.execute(
                "SELECT id,kind,status,error FROM jobs WHERE campaign_id=? ORDER BY created_at", (case["campaign_id"],))]
        return public_data(case)

    def case_action(identifier, kind, key, payload=None):
        case = store.get_case(identifier)
        live_gate(case["backend"])
        return store.enqueue_case_job(identifier, kind, idempotency(key), payload)

    @app.post("/api/cases/{identifier}/reduce", status_code=202)
    def reduce_case(identifier: str, idempotency_key: str | None = Header(None)):
        return case_action(identifier, "reduce", idempotency_key)

    @app.post("/api/cases/{identifier}/confirm", status_code=202)
    def confirm_case(identifier: str, idempotency_key: str | None = Header(None)):
        return case_action(identifier, "confirm", idempotency_key)

    @app.post("/api/cases/{identifier}/rerun", status_code=202)
    def rerun_case(identifier: str, body: RerunRequest = RerunRequest(), idempotency_key: str | None = Header(None)):
        return case_action(identifier, "rerun", idempotency_key, body.model_dump())

    @app.get("/api/cases/{identifier}/export")
    def export_case(identifier: str):
        case = store.get_case(identifier)
        path = artifacts.export_case(case, store.get_campaign(case["campaign_id"]))
        return FileResponse(path, filename=f"{identifier}.zip", media_type="application/zip")

    @app.get("/api/artifacts/{identifier}")
    def get_artifact(identifier: str):
        record = store.get_artifact(identifier)
        path = artifacts.resolve(record)
        headers = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"}
        return FileResponse(path, media_type=record["media_type"], headers=headers)

    @app.get("/api/episodes/{identifier}/trace")
    def get_trace(identifier: str):
        import numpy as np
        with store.connection() as db:
            row = store._required(db, "episodes", identifier)
        episode = store._episode(row)
        manifest = episode.get("artifact_manifest")
        if not manifest:
            raise HTTPException(409, "Episode has no completed trace")
        record = next((f for f in manifest["files"] if f["role"] == "trace"), None)
        if not record:
            raise HTTPException(404, "Trace was not recorded")
        path = artifacts.resolve(dict(record, relative_dir=manifest["relative_dir"]))
        with np.load(path, allow_pickle=False) as arrays:
            data = {key: arrays[key].tolist() for key in arrays.files if arrays[key].size <= 100000}
        return {"episode_id": identifier, "backend": episode["backend"], "arrays": data, **data}

    static_root = Path(web_dir) if web_dir else Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"
    if static_root.is_dir():
        app.mount("/", StaticFiles(directory=static_root, html=True), name="web")
    else:
        @app.get("/")
        def index():
            return {"application": "FailureForge", "message": "Build the web app with npm run build in apps/web, or run its Vite dev server.", "api_docs": "/docs"}
    return app
