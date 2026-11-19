from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .artifacts import ArtifactStore, inspect_bundle, write_json
from .contracts import CampaignSpec, catalog
from .persistence import Store


def services(data_dir):
    root = Path(data_dir).resolve()
    return Store(root / "failureforge.sqlite3"), ArtifactStore(root / "artifacts")


def print_json(value):
    print(json.dumps(value, indent=2, default=str, allow_nan=False))


def make_worker(args, store, artifacts):
    from .worker.engine import Worker
    if args.backend == "synthetic":
        from .simulation.synthetic import SyntheticRunner
        runner = SyntheticRunner()
    else:
        from .worker.supervisor import ProcessRunner
        qualification = Path(args.data_dir).resolve() / "qualification" / "qualification.json"
        if not qualification.exists():
            raise ValueError("Run qualification and review the policy frames before starting the robot worker")
        report = json.loads(qualification.read_text(encoding="utf-8"))
        if not report.get("qualified") or not report.get("scene_review_approved"):
            raise ValueError("Robot qualification or manual scene review has not passed")
        runner = ProcessRunner(args.model_path, qualification, renderer=args.renderer, timeout_seconds=args.episode_timeout)
    return Worker(store, artifacts, runner, backend=args.backend)


def parser():
    root = argparse.ArgumentParser(prog="failureforge", description="Robot-policy failure investigation workbench")
    root.add_argument("--data-dir", default=os.environ.get("FAILUREFORGE_DATA_DIR", "data"))
    sub = root.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="Inspect lightweight runtime readiness; never downloads weights")
    doctor.add_argument("--robotics", action="store_true")
    doctor.add_argument("--model-path", default="models/smolvla_libero")
    sub.add_parser("catalog")
    for name in ("serve", "dev"):
        serve = sub.add_parser(name)
        serve.add_argument("--host", default="127.0.0.1")
        serve.add_argument("--port", type=int, default=8000)
        if name == "dev":
            serve.add_argument("--synthetic", action="store_true", help="Explicitly start the software validation worker")
    worker = sub.add_parser("worker")
    worker.add_argument("--backend", choices=["synthetic", "libero"], required=True)
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--model-path", default="models/smolvla_libero")
    worker.add_argument("--renderer", choices=["egl", "glfw", "osmesa"], default="egl")
    worker.add_argument("--episode-timeout", type=float, default=300)
    search = sub.add_parser("search", help="Validate a campaign specification and enqueue it")
    search.add_argument("--spec", type=Path, required=True)
    search.add_argument("--idempotency-key", default=None)
    for name in ("reduce", "confirm", "rerun"):
        action = sub.add_parser(name)
        action.add_argument("case_id")
        action.add_argument("--idempotency-key", default=None)
    for name in ("cancel", "resume"):
        action = sub.add_parser(name)
        action.add_argument("job_id")
    export = sub.add_parser("export")
    export.add_argument("case_id")
    inspect = sub.add_parser("inspect-bundle")
    inspect.add_argument("path", type=Path)
    report = sub.add_parser("report")
    report.add_argument("campaign_id")
    rerun = sub.add_parser("rerun-bundle", help="Verify an exported bundle and execute a fresh paired rerun")
    rerun.add_argument("path", type=Path)
    rerun.add_argument("--backend", choices=["synthetic", "libero"], default="libero")
    rerun.add_argument("--model-path", default="models/smolvla_libero")
    rerun.add_argument("--renderer", default="egl", choices=["egl", "glfw", "osmesa"])
    rerun.add_argument("--episode-timeout", type=float, default=300)
    qualify = sub.add_parser("qualify")
    qualify.add_argument("--model-path", default="models/smolvla_libero")
    qualify.add_argument("--renderer", choices=["egl", "glfw", "osmesa"], default="egl")
    sub.add_parser("approve-scene-review", help="Record that you inspected the qualification camera images")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        _main(args)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"FailureForge: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _main(args):
    if args.command == "catalog":
        print_json(catalog())
        return
    if args.command == "inspect-bundle":
        result = inspect_bundle(args.path)
        print_json({k: v for k, v in result.items() if k not in ("manifest", "case", "spec")})
        return
    if args.command == "doctor":
        store, _ = services(args.data_dir)
        result = {"application": "FailureForge", "python": sys.version.split()[0], "platform": platform.platform(),
                  "sqlite_version": sqlite3.sqlite_version, "journal_mode": store.journal_mode,
                  "sqlite_note": "WAL enabled on a fixed SQLite runtime" if store.journal_mode == "WAL" else "Rollback journal used because this SQLite runtime lacks the verified WAL fix",
                  "data_dir": str(Path(args.data_dir).resolve()), "worker": store.worker_status(),
                  "robotics": "Not loaded; use --robotics on the execution host"}
        if args.robotics:
            from .simulation import doctor
            result["robotics"] = doctor(model_path=Path(args.model_path))
        print_json(result)
        return
    if args.command in ("serve", "dev"):
        if args.host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("FAILUREFORGE_API_TOKEN"):
            raise ValueError("A non-loopback API requires FAILUREFORGE_API_TOKEN and a TLS reverse proxy")
        worker = None
        if args.command == "dev" and args.synthetic:
            command = [sys.executable, "-m", "failureforge", "--data-dir", args.data_dir, "worker", "--backend", "synthetic"]
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            worker = subprocess.Popen(command, creationflags=flags)
            print("Synthetic validation worker started. Its outcomes are software tests, not robot evidence.", flush=True)
        try:
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(args.data_dir), host=args.host, port=args.port)
        finally:
            if worker:
                worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
        return
    if args.command == "qualify":
        from .simulation import qualify
        print_json(qualify(Path(args.data_dir).resolve() / "qualification", model_path=Path(args.model_path), renderer=args.renderer))
        return
    if args.command == "approve-scene-review":
        from .simulation import approve_scene_review
        print_json(approve_scene_review(Path(args.data_dir).resolve() / "qualification" / "qualification.json"))
        return
    store, artifacts = services(args.data_dir)
    if args.command == "worker":
        worker = make_worker(args, store, artifacts)
        try:
            while True:
                worked = worker.run_once()
                if worked:
                    print_json({"job_id": worker.last_job_id, "error": worker.last_error})
                if args.once:
                    break
                if not worked:
                    time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            if hasattr(worker.runner, "close"):
                worker.runner.close()
        if args.once and worker.last_error:
            raise RuntimeError(worker.last_error)
    elif args.command == "search":
        spec = CampaignSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
        print_json(store.create_campaign(spec, args.idempotency_key or str(uuid.uuid4())))
    elif args.command in ("reduce", "confirm", "rerun"):
        print_json(store.enqueue_case_job(args.case_id, args.command, args.idempotency_key or str(uuid.uuid4()), {"allowance": 2} if args.command == "rerun" else None))
    elif args.command == "cancel":
        store.request_cancel(args.job_id)
        print_json(store.get_job(args.job_id))
    elif args.command == "resume":
        store.resume_job(args.job_id)
        print_json(store.get_job(args.job_id))
    elif args.command == "report":
        campaign = store.get_campaign(args.campaign_id)
        print_json({"id": campaign["id"], "backend": campaign["backend"], "status": campaign["status"], "budget": campaign["budget"],
                    "completed_candidates": sum(c["status"] == "completed" for c in campaign["candidates"]),
                    "observed_failing_candidates": sum((c["score"] or 0) > 0 for c in campaign["candidates"]),
                    "cases": [{k: c.get(k) for k in ("id", "status", "scene_change", "confirmation_summary")} for c in campaign["cases"]]})
    elif args.command == "export":
        case = store.get_case(args.case_id)
        print(artifacts.export_case(case, store.get_campaign(case["campaign_id"])))
    elif args.command == "rerun-bundle":
        source = inspect_bundle(args.path)
        if source["backend"] != args.backend:
            raise ValueError("Bundle backend must match explicitly selected execution backend")
        worker = make_worker(args, store, artifacts)
        try:
            queued = store.import_case_for_rerun(source["spec"], source["case"], source["case_id"])
            worker.run_once(target_job_id=queued["job_id"])
            job = store.get_job(queued["job_id"])
            print_json(dict(queued, status=job["status"], error=job.get("error") or worker.last_error))
            if job["status"] != "succeeded":
                raise RuntimeError(f"Imported rerun {queued['job_id']} is {job['status']}; inspect this job before retrying")
        finally:
            if hasattr(worker.runner, "close"):
                worker.runner.close()
