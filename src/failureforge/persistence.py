"""Durable local queue, fenced writes and transactional rollout allowances."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .contracts import CampaignSpec, ERROR_OUTCOMES, TERMINAL_JOBS, VALID_OUTCOMES, SceneChange, canonical_json, catalog, config_hash, utc_now


class Conflict(ValueError):
    pass


class LeaseLost(Conflict):
    pass


class BudgetExceeded(Conflict):
    pass


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        version = sqlite3.sqlite_version_info
        self.journal_mode = "WAL" if (version >= (3, 51, 3) or (3, 50, 7) <= version < (3, 51, 0) or (3, 44, 6) <= version < (3, 45, 0)) else "DELETE"
        with self.connection() as db:
            schema = db.execute("PRAGMA user_version").fetchone()[0]
            if schema not in (0, 1):
                raise RuntimeError(f"Unsupported database schema {schema}; expected 1")
            db.execute(f"PRAGMA journal_mode={self.journal_mode}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS campaigns (
                  id TEXT PRIMARY KEY,name TEXT NOT NULL,backend TEXT NOT NULL,spec TEXT NOT NULL,
                  limits TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaigns(id),kind TEXT NOT NULL,
                  case_id TEXT,payload TEXT NOT NULL,status TEXT NOT NULL,lease_token TEXT,lease_until REAL,
                  worker_id TEXT,attempt INTEGER NOT NULL DEFAULT 0,cancel_requested INTEGER NOT NULL DEFAULT 0,
                  error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS candidates (
                  id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaigns(id),proposal_index INTEGER NOT NULL,
                  scene_change TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'proposed',
                  score REAL,episode_ids TEXT NOT NULL DEFAULT '[]',UNIQUE(campaign_id,proposal_index));
                CREATE TABLE IF NOT EXISTS episodes (
                  id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaigns(id),job_id TEXT NOT NULL REFERENCES jobs(id),
                  phase TEXT NOT NULL,request TEXT NOT NULL,config_hash TEXT NOT NULL,status TEXT NOT NULL,
                  outcome TEXT,result TEXT,artifact_manifest TEXT,created_at TEXT NOT NULL,completed_at TEXT);
                CREATE TABLE IF NOT EXISTS cases (
                  id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaigns(id),data TEXT NOT NULL,
                  created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts (
                  id TEXT PRIMARY KEY,episode_id TEXT NOT NULL REFERENCES episodes(id),data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS job_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL REFERENCES jobs(id),event TEXT NOT NULL,
                  detail TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workers (
                  id TEXT PRIMARY KEY,backend TEXT NOT NULL,last_seen REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS idempotency (
                  scope TEXT NOT NULL,key TEXT NOT NULL,request_hash TEXT NOT NULL,response TEXT NOT NULL,
                  PRIMARY KEY(scope,key));
                CREATE INDEX IF NOT EXISTS episodes_campaign ON episodes(campaign_id,phase);
                CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status,created_at);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connection(self, write: bool = False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _required(db, table, identifier):
        # Table names are internal constants, never user input.
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        return dict(row)

    def _fence(self, db, job_id, token):
        job = self._required(db, "jobs", job_id)
        if (job["lease_token"] != token or job["status"] not in ("running", "cancelling")
                or (job["lease_until"] or 0) <= time.time()):
            raise LeaseLost("Worker lease expired or was replaced")
        return job

    @staticmethod
    def _event(db, job_id, event, detail=""):
        db.execute("INSERT INTO job_events(job_id,event,detail,created_at) VALUES(?,?,?,?)", (job_id, event, str(detail), utc_now()))

    def _idempotent(self, db, scope, key, request):
        row = db.execute("SELECT * FROM idempotency WHERE scope=? AND key=?", (scope, key)).fetchone()
        if row:
            if row["request_hash"] != config_hash(request):
                raise Conflict("Idempotency key was already used for different input")
            return json.loads(row["response"])
        return None

    @staticmethod
    def _remember(db, scope, key, request, response):
        db.execute("INSERT INTO idempotency VALUES(?,?,?,?)", (scope, key, config_hash(request), canonical_json(response)))

    def _new_job(self, db, campaign_id, kind, case_id=None, payload=None):
        identifier, now = new_id("job"), utc_now()
        db.execute("INSERT INTO jobs(id,campaign_id,kind,case_id,payload,status,created_at,updated_at) VALUES(?,?,?,?,?,'queued',?,?)",
                   (identifier, campaign_id, kind, case_id, canonical_json(payload or {}), now, now))
        self._event(db, identifier, "queued")
        return identifier

    def create_campaign(self, spec: CampaignSpec | dict, idempotency_key: str) -> dict:
        spec = spec if isinstance(spec, CampaignSpec) else CampaignSpec.model_validate(spec)
        data = spec.model_dump(mode="json")
        with self.connection(True) as db:
            existing = self._idempotent(db, "campaign", idempotency_key, data)
            if existing:
                return existing
            identifier, now = new_id("campaign"), utc_now()
            db.execute("INSERT INTO campaigns VALUES(?,?,?,?,?,'queued',?,?)",
                       (identifier, spec.name, spec.backend, canonical_json(data), canonical_json(spec.budget_limits()), now, now))
            job_id = self._new_job(db, identifier, "search")
            result = {"campaign_id": identifier, "job_id": job_id}
            self._remember(db, "campaign", idempotency_key, data, result)
            return result

    def enqueue_case_job(self, case_id, kind, key, payload=None):
        if kind not in ("reduce", "confirm", "rerun"):
            raise ValueError("Unknown case operation")
        request = {"case_id": case_id, "kind": kind, "payload": payload or {}}
        with self.connection(True) as db:
            existing = self._idempotent(db, "case-action", key, request)
            if existing:
                return existing
            case = self._required(db, "cases", case_id)
            campaign = self._required(db, "campaigns", case["campaign_id"])
            if db.execute("SELECT 1 FROM jobs WHERE campaign_id=? AND status IN ('queued','running','cancelling')", (campaign["id"],)).fetchone():
                raise Conflict("This campaign already has active work")
            if kind in ("reduce", "confirm") and db.execute("SELECT 1 FROM jobs WHERE campaign_id=? AND kind=?", (campaign["id"], kind)).fetchone():
                raise Conflict(f"The campaign's {kind} allocation has already been requested; resume an interrupted job instead")
            if kind == "reduce" and db.execute("SELECT 1 FROM jobs WHERE campaign_id=? AND kind='confirm'", (campaign["id"],)).fetchone():
                raise Conflict("Case selection is frozen after confirmation has been requested")
            if kind == "rerun":
                if (payload or {}).get("allowance", 2) != 2:
                    raise ValueError("A rerun explicitly allocates a fresh reference/changed pair")
                limits = json.loads(campaign["limits"])
                limits["rerun"] += 2
                limits["max_attempts"] += 2
                db.execute("UPDATE campaigns SET limits=? WHERE id=?", (canonical_json(limits), campaign["id"]))
            job_id = self._new_job(db, campaign["id"], kind, case_id, payload)
            db.execute("UPDATE campaigns SET status='queued',updated_at=? WHERE id=?", (utc_now(), campaign["id"]))
            result = {"campaign_id": campaign["id"], "job_id": job_id}
            self._remember(db, "case-action", key, request, result)
            return result

    def worker_heartbeat(self, worker_id, backend):
        with self.connection(True) as db:
            db.execute("INSERT INTO workers VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET backend=excluded.backend,last_seen=excluded.last_seen", (worker_id, backend, time.time()))

    def worker_status(self, backend=None):
        with self.connection() as db:
            row = db.execute("SELECT * FROM workers WHERE (? IS NULL OR backend=?) ORDER BY last_seen DESC LIMIT 1", (backend, backend)).fetchone()
        return {"online": bool(row and row["last_seen"] > time.time() - 30), "backend": row["backend"] if row else None,
                "last_seen": row["last_seen"] if row else None, "id": row["id"] if row else None}

    def _recover(self, db):
        for row in db.execute("SELECT * FROM jobs WHERE status IN ('running','cancelling') AND lease_until<=?", (time.time(),)).fetchall():
            status = "cancelled" if row["cancel_requested"] else "interrupted"
            db.execute("UPDATE episodes SET status='error',outcome='worker_lost',completed_at=? WHERE job_id=? AND status='reserved'", (utc_now(), row["id"]))
            db.execute("UPDATE jobs SET status=?,lease_token=NULL,error='Worker lease expired',updated_at=? WHERE id=?", (status, utc_now(), row["id"]))
            db.execute("UPDATE campaigns SET status=?,updated_at=? WHERE id=?", (status, utc_now(), row["campaign_id"]))
            self._event(db, row["id"], status, "Expired lease; uncertain starts remain charged")

    def recover_expired(self):
        with self.connection(True) as db:
            self._recover(db)

    def claim_job(self, backend, worker_id, lease_seconds=60, target_job_id=None):
        with self.connection(True) as db:
            self._recover(db)
            # One simulator owner globally, including when different backend workers exist.
            if db.execute("SELECT 1 FROM jobs WHERE status IN ('running','cancelling')").fetchone():
                return None
            row = db.execute("SELECT j.* FROM jobs j JOIN campaigns c ON c.id=j.campaign_id WHERE j.status='queued' AND c.backend=? AND (? IS NULL OR j.id=?) ORDER BY j.created_at LIMIT 1", (backend, target_job_id, target_job_id)).fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET status='running',lease_token=?,lease_until=?,worker_id=?,attempt=attempt+1,updated_at=? WHERE id=?", (token, time.time() + lease_seconds, worker_id, utc_now(), row["id"]))
            db.execute("UPDATE campaigns SET status='running',updated_at=? WHERE id=?", (utc_now(), row["campaign_id"]))
            self._event(db, row["id"], "running", f"worker={worker_id}")
            result = self._required(db, "jobs", row["id"])
            result["payload"] = json.loads(result["payload"])
            return result

    def heartbeat(self, job_id, token, lease_seconds=60):
        with self.connection(True) as db:
            job = self._fence(db, job_id, token)
            db.execute("UPDATE jobs SET lease_until=?,updated_at=? WHERE id=?", (time.time() + lease_seconds, utc_now(), job_id))
            db.execute("UPDATE workers SET last_seen=? WHERE id=?", (time.time(), job["worker_id"]))

    def cancel_requested(self, job_id, token):
        with self.connection() as db:
            return bool(self._fence(db, job_id, token)["cancel_requested"])

    def request_cancel(self, job_id):
        with self.connection(True) as db:
            job = self._required(db, "jobs", job_id)
            if job["status"] in TERMINAL_JOBS:
                return
            status = "cancelled" if job["status"] == "queued" else "cancelling"
            db.execute("UPDATE jobs SET cancel_requested=1,status=?,updated_at=? WHERE id=?", (status, utc_now(), job_id))
            db.execute("UPDATE campaigns SET status=?,updated_at=? WHERE id=?", (status, utc_now(), job["campaign_id"]))
            self._event(db, job_id, status, "User requested cancellation")

    def resume_job(self, job_id):
        with self.connection(True) as db:
            self._recover(db)
            job = self._required(db, "jobs", job_id)
            if job["status"] != "interrupted":
                raise Conflict("Only an interrupted job can resume")
            if db.execute("SELECT 1 FROM jobs WHERE campaign_id=? AND status IN ('running','queued','cancelling')", (job["campaign_id"],)).fetchone():
                raise Conflict("Campaign already has active work")
            db.execute("UPDATE jobs SET status='queued',cancel_requested=0,error=NULL,updated_at=? WHERE id=?", (utc_now(), job_id))
            db.execute("UPDATE campaigns SET status='queued',updated_at=? WHERE id=?", (utc_now(), job["campaign_id"]))
            self._event(db, job_id, "queued", "Explicit resume; previous attempts stay charged")

    @staticmethod
    def _budget(db, campaign):
        rows = db.execute("SELECT phase,status,outcome,COUNT(*) n FROM episodes WHERE campaign_id=? GROUP BY phase,status,outcome", (campaign["id"],)).fetchall()
        phases = {name: {"attempted": 0, "completed": 0, "reserved": 0, "errors": 0} for name in ("baseline", "search", "reduction", "confirmation", "rerun")}
        for row in rows:
            p = phases[row["phase"]]
            p["attempted"] += row["n"]
            if row["status"] == "reserved":
                p["reserved"] += row["n"]
            elif row["outcome"] in VALID_OUTCOMES:
                p["completed"] += row["n"]
            elif row["outcome"] in ERROR_OUTCOMES:
                p["errors"] += row["n"]
        result = {k: sum(p[k] for p in phases.values()) for k in ("attempted", "completed", "reserved", "errors")}
        retries = db.execute("SELECT COUNT(*) FROM episodes WHERE campaign_id=? AND json_extract(request,'$._retry')=1", (campaign["id"],)).fetchone()[0]
        result.update(retries=retries, phases=phases, limits=json.loads(campaign["limits"]))
        return result

    def reserve_episode(self, job_id, token, phase, request):
        if phase not in ("baseline", "search", "reduction", "confirmation", "rerun"):
            raise ValueError("Unknown budget phase")
        with self.connection(True) as db:
            job = self._fence(db, job_id, token)
            if job["cancel_requested"]:
                raise Conflict("Job cancellation requested")
            campaign = self._required(db, "campaigns", job["campaign_id"])
            budget = self._budget(db, campaign)
            active = budget["phases"][phase]
            if budget["errors"] > 2 or budget["attempted"] >= budget["limits"]["max_attempts"]:
                raise BudgetExceeded("Campaign attempt or shared infrastructure retry limit reached")
            if active["completed"] + active["reserved"] >= budget["limits"][phase]:
                raise BudgetExceeded(f"{phase} allowance exhausted")
            if phase == "rerun":
                consumed = db.execute("SELECT COUNT(*) FROM episodes WHERE job_id=?", (job_id,)).fetchone()[0]
                if consumed >= 2:
                    raise BudgetExceeded("Fresh rerun has an explicit two-attempt allowance")
            request = dict(request)
            previous = db.execute("SELECT 1 FROM episodes WHERE job_id=? AND json_extract(request,'$.request_key')=? AND status='error'", (job_id, request.get("request_key"))).fetchone()
            if previous and budget["retries"] >= budget["limits"]["infrastructure_retries"]:
                raise BudgetExceeded("Campaign's shared infrastructure retry allowance exhausted")
            request["_retry"] = bool(previous)
            identifier = new_id("episode")
            declared = catalog()
            scientific_config = {key: request.get(key) for key in ("state_id", "seed", "scene_change", "max_steps", "control_hz")}
            scientific_config.update(backend=campaign["backend"], task=declared["task"], policy=declared["policy"])
            db.execute("INSERT INTO episodes(id,campaign_id,job_id,phase,request,config_hash,status,created_at) VALUES(?,?,?,?,?,?,'reserved',?)",
                       (identifier, campaign["id"], job_id, phase, canonical_json(request), config_hash(scientific_config), utc_now()))
            self._event(db, job_id, "episode_started", identifier)
            return identifier

    def complete_episode(self, job_id, token, episode_id, result, artifact_manifest):
        if result.get("outcome") not in VALID_OUTCOMES:
            raise ValueError("Only valid scientific outcomes can complete an episode")
        with self.connection(True) as db:
            self._fence(db, job_id, token)
            episode = self._required(db, "episodes", episode_id)
            if episode["job_id"] != job_id or episode["status"] != "reserved":
                raise Conflict("Episode is not reserved by this job")
            if artifact_manifest.get("episode_id") != episode_id or artifact_manifest.get("lease_token") != token:
                raise Conflict("Artifact attempt identity does not match episode lease")
            db.execute("UPDATE episodes SET status='completed',outcome=?,result=?,artifact_manifest=?,completed_at=? WHERE id=?",
                       (result["outcome"], canonical_json(result), canonical_json(artifact_manifest), utc_now(), episode_id))
            for artifact in artifact_manifest["files"]:
                data = dict(artifact, relative_dir=artifact_manifest["relative_dir"])
                db.execute("INSERT INTO artifacts VALUES(?,?,?)", (artifact["id"], episode_id, canonical_json(data)))
            self._event(db, job_id, "episode_completed", episode_id)

    def fail_episode(self, job_id, token, episode_id, outcome, error):
        if outcome not in ERROR_OUTCOMES | {"cancelled", "invalid_scene"}:
            raise ValueError("Unknown incomplete/error outcome")
        with self.connection(True) as db:
            self._fence(db, job_id, token)
            episode = self._required(db, "episodes", episode_id)
            if episode["job_id"] != job_id or episode["status"] != "reserved":
                raise Conflict("Episode is not reserved by this job")
            db.execute("UPDATE episodes SET status='error',outcome=?,result=?,completed_at=? WHERE id=?", (outcome, canonical_json({"outcome": outcome, "error": str(error)[:2000]}), utc_now(), episode_id))
            self._event(db, job_id, "episode_error", f"{episode_id}: {outcome}")

    def add_candidate(self, job_id, token, index, scene_change, reason):
        with self.connection(True) as db:
            job = self._fence(db, job_id, token)
            existing = db.execute("SELECT * FROM candidates WHERE campaign_id=? AND proposal_index=?", (job["campaign_id"], index)).fetchone()
            if existing:
                if json.loads(existing["scene_change"]) != scene_change:
                    raise Conflict("Persisted proposal changed during resume")
                return existing["id"]
            identifier = new_id("candidate")
            db.execute("INSERT INTO candidates(id,campaign_id,proposal_index,scene_change,reason) VALUES(?,?,?,?,?)", (identifier, job["campaign_id"], index, canonical_json(scene_change), reason))
            return identifier

    def complete_candidate(self, job_id, token, candidate_id, episode_ids, score):
        with self.connection(True) as db:
            job = self._fence(db, job_id, token)
            if job["kind"] != "search":
                raise Conflict("Only a search job can score a candidate")
            row = self._required(db, "candidates", candidate_id)
            if row["campaign_id"] != job["campaign_id"]:
                raise Conflict("Candidate belongs to another campaign")
            if row["status"] == "completed" and json.loads(row["episode_ids"]) != episode_ids:
                raise Conflict("A completed candidate's episode pairing is immutable")
            spec = json.loads(self._required(db, "campaigns", job["campaign_id"])["spec"])
            episodes = [self._required(db, "episodes", identifier) for identifier in episode_ids]
            if len(episodes) != 2 or any(e["status"] != "completed" or e["campaign_id"] != job["campaign_id"] for e in episodes):
                raise Conflict("Both candidate episodes must be complete")
            requests = [json.loads(e["request"]) for e in episodes]
            scene = json.loads(row["scene_change"])
            if any(e["job_id"] != job_id or e["phase"] != "search" or
                   request.get("candidate_id") != candidate_id or request.get("scene_change") != scene or
                   request.get("condition") != "changed" for e, request in zip(episodes, requests)):
                raise Conflict("Candidate evidence must match its search job, scene, identifier, and changed condition")
            if {request["state_id"] for request in requests} != set(spec["state_ids"]):
                raise Conflict("Candidate state bank does not match")
            actual = sum(e["outcome"] != "success" for e in episodes) / 2
            if actual != score:
                raise Conflict("Candidate score disagrees with recorded task outcomes")
            db.execute("UPDATE candidates SET status='completed',score=?,episode_ids=? WHERE id=?", (actual, canonical_json(episode_ids), candidate_id))

    def save_case(self, job_id, token, case_data):
        with self.connection(True) as db:
            job = self._fence(db, job_id, token)
            existing = db.execute("SELECT id FROM cases WHERE campaign_id=?", (job["campaign_id"],)).fetchone()
            if existing:
                return existing["id"]
            identifier, now = new_id("case"), utc_now()
            data = dict(case_data, id=identifier, campaign_id=job["campaign_id"])
            db.execute("INSERT INTO cases VALUES(?,?,?,?,?)", (identifier, job["campaign_id"], canonical_json(data), now, now))
            return identifier

    def update_case(self, job_id, token, case_id, updates):
        with self.connection(True) as db:
            job = self._fence(db, job_id, token)
            row = self._required(db, "cases", case_id)
            if row["campaign_id"] != job["campaign_id"]:
                raise Conflict("Case belongs to another campaign")
            data = json.loads(row["data"])
            data.update(updates)
            db.execute("UPDATE cases SET data=?,updated_at=? WHERE id=?", (canonical_json(data), utc_now(), case_id))

    def finish_job(self, job_id, token, status, error=None):
        if status not in TERMINAL_JOBS:
            raise ValueError("Invalid terminal job state")
        with self.connection(True) as db:
            job = self._fence(db, job_id, token)
            if job["cancel_requested"]:
                status = "cancelled"
            remaining = db.execute("SELECT COUNT(*) FROM episodes WHERE job_id=? AND status='reserved'", (job_id,)).fetchone()[0]
            if remaining and status == "succeeded":
                raise Conflict("Cannot succeed with incomplete episodes")
            if remaining:
                db.execute("UPDATE episodes SET status='error',outcome=?,completed_at=? WHERE job_id=? AND status='reserved'", ("cancelled" if status == "cancelled" else "worker_lost", utc_now(), job_id))
            db.execute("UPDATE jobs SET status=?,error=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?", (status, str(error)[:2000] if error else None, utc_now(), job_id))
            db.execute("UPDATE campaigns SET status=?,updated_at=? WHERE id=?", (status, utc_now(), job["campaign_id"]))
            self._event(db, job_id, status, error or "")

    def get_job(self, identifier):
        with self.connection() as db:
            job = self._required(db, "jobs", identifier)
            job["payload"] = json.loads(job["payload"])
            job["events"] = [dict(r) for r in db.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id", (identifier,))]
            return job

    def list_candidates(self, campaign_id):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM candidates WHERE campaign_id=? ORDER BY proposal_index", (campaign_id,)).fetchall()
        return [dict(dict(r), index=r["proposal_index"], scene_change=json.loads(r["scene_change"]), episode_ids=json.loads(r["episode_ids"])) for r in rows]

    @staticmethod
    def _episode(row):
        request = json.loads(row["request"])
        result = json.loads(row["result"]) if row["result"] else {}
        manifest = json.loads(row["artifact_manifest"]) if row["artifact_manifest"] else None
        files = {f["role"]: f"/api/artifacts/{f['id']}" for f in manifest["files"]} if manifest else {}
        return dict(dict(row), **{"request": request, "result": result, "artifact_manifest": manifest}, **{
            "state_id": request["state_id"], "seed": request["seed"], "condition": request.get("condition", "changed"),
            "scene_change": request["scene_change"], "candidate_id": request.get("candidate_id"), "steps": result.get("steps", 0),
            "elapsed_seconds": result.get("elapsed_seconds", 0), "backend": result.get("backend"), "artifacts": files,
        })

    def list_episodes(self, campaign_id, phase=None):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM episodes WHERE campaign_id=? AND (? IS NULL OR phase=?) ORDER BY created_at,id", (campaign_id, phase, phase)).fetchall()
        return [self._episode(r) for r in rows]

    def get_case(self, identifier):
        with self.connection() as db:
            row = self._required(db, "cases", identifier)
            data = json.loads(row["data"])
            campaign = self._required(db, "campaigns", row["campaign_id"])
        data.update(id=row["id"], campaign_id=row["campaign_id"], backend=campaign["backend"], created_at=row["created_at"], updated_at=row["updated_at"])
        data["spec"] = json.loads(campaign["spec"])
        # Keep all executions visible, including original, reduction attempts and disagreements.
        data["episodes"] = self.list_episodes(row["campaign_id"])
        return data

    def get_campaign(self, identifier):
        with self.connection() as db:
            row = self._required(db, "campaigns", identifier)
            row["budget"] = self._budget(db, row)
            row["spec"] = json.loads(row["spec"])
            row["limits"] = json.loads(row["limits"])
            job_ids = [r[0] for r in db.execute("SELECT id FROM jobs WHERE campaign_id=? ORDER BY created_at", (identifier,))]
            case_ids = [r[0] for r in db.execute("SELECT id FROM cases WHERE campaign_id=?", (identifier,))]
        row["candidates"] = self.list_candidates(identifier)
        row["episodes"] = self.list_episodes(identifier)
        row["jobs"] = [self.get_job(i) for i in job_ids]
        row["cases"] = [self.get_case(i) for i in case_ids]
        return row

    def list_campaigns(self):
        with self.connection() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM campaigns ORDER BY created_at DESC LIMIT 100")]
        return [self.get_campaign(i) for i in ids]

    def get_artifact(self, identifier):
        with self.connection() as db:
            row = self._required(db, "artifacts", identifier)
        return dict(json.loads(row["data"]), episode_id=row["episode_id"])

    def backup(self, destination):
        with self.connection() as source, sqlite3.connect(destination) as target:
            source.backup(target)

    def import_case_for_rerun(self, spec, case_data, source_case_id):
        """Atomically enqueue a verified bundle's data; never claim unrelated work."""
        spec = CampaignSpec.model_validate(spec)
        scene = SceneChange.model_validate(case_data["scene_change"]).model_dump()
        for key, value in scene.items():
            low, high = getattr(spec.domain, key)
            if not low <= value <= high:
                raise ValueError("Imported case is outside its declared domain")
        failing = case_data["failure_state_ids"]
        if not failing or any(type(s) is not int or s not in spec.state_ids for s in failing):
            raise ValueError("Imported witness has an invalid failing-state bank")
        with self.connection(True) as db:
            if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running','cancelling')").fetchone():
                raise Conflict("Bundle rerun requires an idle queue")
            campaign_id, case_id, now = new_id("campaign"), new_id("case"), utc_now()
            limits = spec.budget_limits()
            limits.update(baseline=0, search=0, reduction=0, confirmation=0, rerun=2, max_attempts=2, infrastructure_retries=0)
            db.execute("INSERT INTO campaigns VALUES(?,?,?,?,?,'queued',?,?)", (campaign_id, f"Rerun of {source_case_id}", spec.backend,
                       canonical_json(spec.model_dump(mode="json")), canonical_json(limits), now, now))
            data = {"id": case_id, "campaign_id": campaign_id, "backend": spec.backend, "status": "imported_for_rerun",
                    "scene_change": scene, "failure_state_ids": failing, "pairs": [], "episode_ids": [],
                    "source_case_id": source_case_id, "reduction_history": [], "confirmation_summary": None}
            db.execute("INSERT INTO cases VALUES(?,?,?,?,?)", (case_id, campaign_id, canonical_json(data), now, now))
            job_id = self._new_job(db, campaign_id, "rerun", case_id, {"allowance": 2})
            return {"campaign_id": campaign_id, "case_id": case_id, "job_id": job_id}
