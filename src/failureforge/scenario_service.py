"""Project-scoped scenario generation, review and atomic paired execution."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import Field, ValidationError

from .contracts import canonical_json, config_hash, utc_now
from .persistence import Conflict, new_id
from .project_runs import MAX_SUITE_TESTS, ProjectTest, Revision, project_adapters
from .project_solver import MODELS
from .projects import IntakeModel
from .scenario_core import OPERATIONS, CandidateDraft, build_context, compile_candidate
from .scenario_provider import GENERATE_TIMEOUT, PROMPT_VERSION, TARGET_CASES, LocalProvider, ProviderError
from .scenario_results import applied_change, recorded_outcome, verified_run


class Generate(Revision):
    task: str = Field(default="", max_length=2000)
    baseline_run_id: str | None = Field(default=None, min_length=1, max_length=100)
    run_supported: bool = Field(default=False, strict=True)


class Review(Revision):
    confirmed: bool = Field(strict=True)


class Execute(Review):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_note: str = Field(default="", max_length=600)


class ReferenceImport(Revision):
    asset_id: str = Field(pattern=r"^asset_[a-f0-9]{32}$")


class ReferenceFile(IntakeModel):
    adapter: Literal["structural_beam", "packaging_lift", "packaging_lift_timed_v2"]
    inputs: dict
    label: str | None = Field(default=None, min_length=1, max_length=120)


def _key(key):
    if not key or not 8 <= len(key) <= 200:
        raise HTTPException(422, "Supply an Idempotency-Key of 8 to 200 characters.")
    return key


class ScenarioService:
    def __init__(self, runs, provider=None):
        self.runs, self.projects, self.store = runs, runs.projects, runs.store
        self.provider = provider or LocalProvider()
        self.stop, self.wake = threading.Event(), threading.Event()
        self.thread = None
        with self.store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scenario_batches (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    revision INTEGER NOT NULL, task TEXT NOT NULL, baseline_run_id TEXT,
                    context TEXT NOT NULL, model TEXT NOT NULL, digest TEXT NOT NULL,
                    prompt_version TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
                    clarifications TEXT NOT NULL DEFAULT '[]', usage TEXT, lease TEXT, expires REAL,
                    created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS scenario_history ON scenario_batches(project_id,created_at);
                CREATE TABLE IF NOT EXISTS scenario_candidates (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES scenario_batches(id),
                    draft TEXT NOT NULL, dismissed INTEGER NOT NULL DEFAULT 0,
                    execution TEXT, review TEXT);
                CREATE INDEX IF NOT EXISTS scenario_batch_cards ON scenario_candidates(batch_id);
                CREATE TABLE IF NOT EXISTS scenario_imports (
                    run_id TEXT PRIMARY KEY REFERENCES project_runs(id), asset_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL);
            """)
        with self.store.connection(True) as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(scenario_batches)")}
            for name, definition in (("run_supported", "INTEGER NOT NULL DEFAULT 0"), ("target", "INTEGER"),
                                     ("execution_error", "TEXT")):
                if name not in columns:
                    db.execute(f"ALTER TABLE scenario_batches ADD COLUMN {name} {definition}")

    def start(self):
        self.stop = threading.Event()
        self.worker_id = new_id("planner")
        self.thread = threading.Thread(target=self._worker, args=(self.worker_id, self.stop),
                                       daemon=True, name="scenario-generation")
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            with self.store.connection(True) as db:
                db.execute("""UPDATE scenario_batches SET status='interrupted',error='The generation worker stopped. Generate again.',
                           expires=NULL,lease=NULL WHERE status='running' AND lease GLOB ?""", (self.worker_id + "-*",))
            self.thread.join(1)

    def _project(self, db, identifier, revision):
        project = self.projects._get(db, identifier)
        if project["revision"] != revision:
            raise Conflict("The project changed. Reload its current revision before continuing.")
        return project

    def _context(self, db, project, baseline_id, task):
        baseline = self.runs.get_in_transaction(db, project["id"], baseline_id) if baseline_id else None
        try:
            packet = build_context(project, baseline, task=task)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        # An imported definition has a traceable origin even when other JSON files exist.
        if baseline_id:
            origin = db.execute("SELECT asset_id,sha256 FROM scenario_imports WHERE run_id=?", (baseline_id,)).fetchone()
            if origin:
                record, _ = self.projects.asset_in_transaction(db, project["id"], origin["asset_id"])
                if record["sha256"] != origin["sha256"]:
                    raise Conflict("The imported reference file changed. Import the design again.")
                packet["baseline"]["source_asset"] = dict(origin)
                packet.pop("context_hash")
                packet["context_hash"] = config_hash(packet)
        return packet

    @staticmethod
    def _batch(db, project_id, batch_id):
        row = db.execute("""SELECT id,revision,task,baseline_run_id,model,digest,prompt_version,
                            status,error,clarifications,usage,created_at,run_supported,target,execution_error FROM scenario_batches
                            WHERE id=? AND project_id=?""", (batch_id, project_id)).fetchone()
        if row is None:
            raise KeyError(batch_id)
        result = dict(row)
        result["run_supported"] = bool(row["run_supported"])
        result["clarifications"] = json.loads(row["clarifications"])
        result["usage"] = json.loads(row["usage"]) if row["usage"] else {}
        result["candidates"] = []
        for c in db.execute("SELECT * FROM scenario_candidates WHERE batch_id=? ORDER BY rowid", (batch_id,)):
            draft = json.loads(c["draft"])
            operation = OPERATIONS.get(draft["operation_id"])
            review = json.loads(c["review"]) if c["review"] else None
            family = review["family_key"] if review else operation.family if operation and not draft["missing_capability"] else None
            result["candidates"].append({"id": c["id"], "draft": draft, "dismissed": bool(c["dismissed"]),
                "review": review, "family_key": family, "execution": json.loads(c["execution"]) if c["execution"] else None})
        return result

    def history(self, project_id):
        with self.store.connection() as db:
            self.store._required(db, "projects", project_id)
            ids = db.execute("SELECT id FROM scenario_batches WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 30",
                             (project_id,)).fetchall()
            batches = [self._batch(db, project_id, r["id"]) for r in ids]
        return {"provider": self.provider.status(), "batches": batches}

    def generate(self, project_id, body, key):
        scope, request = "scenario-generate:" + project_id, body.model_dump()
        if not body.run_supported:
            request.pop("run_supported")  # Retain the original request hash for existing retries.
        elif not body.baseline_run_id:
            raise HTTPException(422, "Choose a completed reference before requesting automatic tests.")
        provider = self.provider.status()
        with self.store.connection(True) as db:
            previous = self.store._idempotent(db, scope, key, request)
            if previous:
                return self._batch(db, project_id, previous["id"])
            project = self._project(db, project_id, body.expected_revision)
            if not provider["available"]:
                raise HTTPException(503, provider["detail"])
            packet = self._context(db, project, body.baseline_run_id, body.task)
            pending = db.execute("SELECT COUNT(*) FROM scenario_batches WHERE status IN ('queued','running')").fetchone()[0]
            if pending >= 5:
                raise HTTPException(429, "Five generations are already pending. Wait for one to finish.")
            batch_id = new_id("discovery")
            db.execute("""INSERT INTO scenario_batches(id,project_id,revision,task,baseline_run_id,context,
                          model,digest,prompt_version,status,created_at,run_supported,target) VALUES(?,?,?,?,?,?,?,?,?,'queued',?,?,?)""",
                       (batch_id, project_id, body.expected_revision, body.task, body.baseline_run_id,
                        canonical_json(packet), provider["model"], provider["digest"], PROMPT_VERSION, utc_now(),
                        int(body.run_supported), TARGET_CASES))
            self.store._remember(db, scope, key, request, {"id": batch_id})
            batch = self._batch(db, project_id, batch_id)
        self.wake.set()
        return batch

    def _claim(self, worker_id, stop):
        with self.store.connection() as db:
            needed = db.execute("""SELECT 1 FROM scenario_batches WHERE status='queued' OR
                                   (status='running' AND expires<=?) LIMIT 1""", (time.time(),)).fetchone()
        if not needed:
            return None
        with self.store.connection(True) as db:
            if stop.is_set():
                return None
            db.execute("""UPDATE scenario_batches SET status='interrupted',error='The generation worker stopped. Generate again.',
                          lease=NULL,expires=NULL WHERE status='running' AND expires<=?""", (time.time(),))
            row = db.execute("SELECT * FROM scenario_batches WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return None
            lease = worker_id + "-" + new_id("lease")
            db.execute("UPDATE scenario_batches SET status='running',lease=?,expires=? WHERE id=?",
                       (lease, time.time() + GENERATE_TIMEOUT * 2 + 90, row["id"]))
        return dict(row), lease

    def _run(self, row, lease):
        packet = json.loads(row["context"])
        try:
            batch, usage = self.provider.generate(packet, row["digest"])
            error, candidates, seen = None, [], set()
            for draft in batch.candidates:
                report = compile_candidate(packet, draft)
                identity = report["instance_hash"]
                if identity and identity in seen:
                    continue
                seen.add(identity)
                candidates.append(draft.model_dump_json())
            clarifications = batch.clarifications
        except ProviderError as exc:
            error, candidates, clarifications, usage = str(exc), [], [], exc.usage or {}
        except Exception:
            logging.getLogger(__name__).exception("Scenario generation failed for batch %s", row["id"])
            error, candidates, clarifications, usage = "Scenario generation could not be completed.", [], [], {}
        with self.store.connection(True) as db:
            changed = db.execute("""UPDATE scenario_batches SET status=?,error=?,clarifications=?,usage=?,
                lease=NULL,expires=NULL WHERE id=? AND lease=? AND status='running' AND expires>?""",
                ("error" if error else "completed", error, canonical_json(clarifications), canonical_json(usage),
                 row["id"], lease, time.time())).rowcount
            if changed:
                db.executemany("INSERT INTO scenario_candidates(id,batch_id,draft) VALUES(?,?,?)",
                               [(new_id("scenario"), row["id"], item) for item in candidates])
                if row["run_supported"] and not error:
                    # A changed design can block execution after inference. Preserve the proposals.
                    db.execute("SAVEPOINT scenario_queue")
                    try:
                        self._queue_batch(db, row["project_id"], row["id"], row["revision"])
                    except (Conflict, HTTPException, KeyError, ValueError) as exc:
                        db.execute("ROLLBACK TO scenario_queue")
                        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                        db.execute("UPDATE scenario_batches SET execution_error=? WHERE id=?",
                                   (str(detail)[:600], row["id"]))
                    db.execute("RELEASE scenario_queue")
        self.runs.wake.set()

    def _worker(self, worker_id, stop):
        while not stop.is_set():
            try:
                claimed = self._claim(worker_id, stop)
                if claimed:
                    self._run(*claimed)
                    continue
            except Exception:
                logging.getLogger(__name__).exception("Scenario queue poll failed")
            self.wake.wait(1)
            self.wake.clear()

    @staticmethod
    def _candidate(db, project_id, candidate_id):
        row = db.execute("""SELECT c.*, b.context,b.revision,b.baseline_run_id,b.task FROM scenario_candidates c
            JOIN scenario_batches b ON c.batch_id=b.id WHERE c.id=? AND b.project_id=?""", (candidate_id, project_id)).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return row

    def _review(self, db, project_id, row, body):
        project = self._project(db, project_id, body.expected_revision)
        if row["revision"] != project["revision"]:
            raise Conflict("This suggestion belongs to an older project revision. Generate a new batch.")
        if row["dismissed"]:
            raise Conflict("This suggestion was dismissed.")
        packet = self._context(db, project, row["baseline_run_id"], row["task"])
        if json.loads(row["context"])["context_hash"] != packet["context_hash"]:
            raise Conflict("The source context or available operations changed. Generate a fresh batch.")
        return project, compile_candidate(packet, CandidateDraft.model_validate_json(row["draft"]), body.confirmed)

    def preview(self, project_id, candidate_id, body):
        with self.store.connection() as db:
            row = self._candidate(db, project_id, candidate_id)
            return self._review(db, project_id, row, body)[1]

    def _batch_source(self, db, project_id, batch_id):
        batch = db.execute("SELECT * FROM scenario_batches WHERE id=? AND project_id=?",
                           (batch_id, project_id)).fetchone()
        if batch is None:
            raise KeyError(batch_id)
        return batch

    def _current_packet(self, db, project, batch):
        if project["revision"] != batch["revision"]:
            raise Conflict("The project changed. Generate a batch against its current reference.")
        packet = self._context(db, project, batch["baseline_run_id"], batch["task"])
        if json.loads(batch["context"])["context_hash"] != packet["context_hash"]:
            raise Conflict("The reference or simulator capabilities changed. Generate a fresh batch.")
        return packet

    def _queue_batch(self, db, project_id, batch_id, revision):
        batch = self._batch_source(db, project_id, batch_id)
        if batch["status"] != "completed":
            raise Conflict("Wait for scenario generation to finish.")
        project = self._project(db, project_id, revision)
        packet = self._current_packet(db, project, batch)
        plans, tests, references = [], [], {}
        for card in db.execute("""SELECT id,draft FROM scenario_candidates
                                  WHERE batch_id=? AND dismissed=0 AND execution IS NULL ORDER BY rowid""", (batch_id,)):
            draft = CandidateDraft.model_validate_json(card["draft"])
            plan = compile_candidate(packet, draft, confirmed=True)
            if plan["state"] != "ready":
                continue
            reference = ProjectTest.model_validate(plan["reference"])
            identity = config_hash(reference.model_dump(exclude={"label"}))
            if identity not in references:
                references[identity] = len(tests)
                tests.append(reference)
            variant_index = len(tests)
            tests.append(ProjectTest.model_validate({**plan["variant"], "label": draft.title}))
            plans.append((card["id"], plan, references[identity], variant_index))
        if not plans:
            return
        if len(tests) > MAX_SUITE_TESTS:
            raise Conflict("This batch exceeds the supported suite size.")
        receipt = self.runs._enqueue(db, project, tests)
        db.execute("INSERT INTO project_named_suites VALUES(?,?)",
                   (receipt["suite_id"], f"Scenario tests · {len(plans)} what-ifs"))
        for identifier, plan, ref, variant in plans:
            execution = {"suite_id": receipt["suite_id"], "runs": [receipt["ids"][ref], receipt["ids"][variant]]}
            reviewed = {**plan, "approval_mode": "batch", "confirmed_at": utc_now(), "review_note": ""}
            db.execute("UPDATE scenario_candidates SET execution=?,review=? WHERE id=?",
                       (canonical_json(execution), canonical_json(reviewed), identifier))

    def execute_all(self, project_id, batch_id, body, key):
        scope, request = "scenario-execute-batch:" + project_id, {"batch_id": batch_id, **body.model_dump()}
        with self.store.connection(True) as db:
            if not self.store._idempotent(db, scope, key, request):
                self._queue_batch(db, project_id, batch_id, body.expected_revision)
                db.execute("UPDATE scenario_batches SET execution_error=NULL WHERE id=?", (batch_id,))
                self.store._remember(db, scope, key, request, {"batch_id": batch_id})
        self.runs.wake.set()
        return self.results(project_id, batch_id)

    def results(self, project_id, batch_id):
        with self.store.connection() as db:
            db.execute("BEGIN")
            batch = self._batch_source(db, project_id, batch_id)
            runtimes = json.loads(batch["context"]).get("runtime_hashes", {})
            cards = db.execute("SELECT * FROM scenario_candidates WHERE batch_id=? ORDER BY rowid", (batch_id,)).fetchall()
            packet, stale = None, None
            if any(not c["execution"] and not c["dismissed"] for c in cards):
                try:
                    project = self.projects._get(db, project_id)
                    packet = self._current_packet(db, project, batch)
                except (Conflict, HTTPException, KeyError) as exc:
                    stale = str(exc.detail if isinstance(exc, HTTPException) else exc)
            records, rows = {}, []
            for c in cards:
                draft = CandidateDraft.model_validate_json(c["draft"])
                plan = json.loads(c["review"]) if c["review"] else None
                execution = json.loads(c["execution"]) if c["execution"] else None
                measurement = ref = variant = suite = None
                if execution:
                    ref, variant = execution["runs"]
                    suite = execution["suite_id"]
                    for identifier in (ref, variant):
                        if identifier not in records:
                            records[identifier] = verified_run(self.runs, db, project_id, identifier)
                    expected = runtimes.get(plan["variant"]["adapter"])
                    state, reason, measurement = recorded_outcome(records[ref], records[variant], expected)
                elif c["dismissed"]:
                    state, reason = "dismissed", "Dismissed during review."
                elif stale:
                    state, reason = "stale", stale
                else:
                    plan = compile_candidate(packet, draft, confirmed=True)
                    state, reason = plan["state"], plan["reason"]
                rows.append({"candidate_id": c["id"], "title": draft.title, "hypothesis": draft.hypothesis,
                             "family_key": plan.get("family_key") if plan else None,
                             "assumptions": draft.assumptions, "state": state, "reason": reason,
                             "reference_run_id": ref, "variant_run_id": variant, "suite_id": suite,
                             "measurement": measurement, "applied_change": applied_change(plan)})
        states = [row["state"] for row in rows]
        passed, failed = states.count("passed"), states.count("failed")
        counts = {"proposed": len(rows), "submitted": sum(bool(row["variant_run_id"]) for row in rows),
                  "assessed": passed + failed, "passed": passed, "failed": failed,
                  "measurement_only": states.count("measurement_only"), "inconclusive": states.count("inconclusive"),
                  "pending": states.count("queued") + states.count("running"),
                  "blocked": sum(states.count(s) for s in ("invalid","needs_information","needs_capability","stale"))}
        return {"batch_id": batch_id, "target": batch["target"], "generation_status": batch["status"],
                "run_supported": bool(batch["run_supported"]), "execution_error": batch["execution_error"],
                "rows": rows, "counts": counts}

    def execute(self, project_id, candidate_id, body, key):
        scope = "scenario-execute:" + project_id
        request = {"candidate_id": candidate_id, **body.model_dump(exclude_defaults=True)}
        with self.store.connection(True) as db:
            previous = self.store._idempotent(db, scope, key, request)
            if previous:
                return previous
            row = self._candidate(db, project_id, candidate_id)
            project, report = self._review(db, project_id, row, body)
            if not body.confirmed or report["state"] != "ready" or report["fingerprint"] != body.fingerprint:
                raise Conflict("Review and confirm the current executable preview before running.")
            if row["execution"]:
                if json.loads(row["review"]).get("review_note", "") != body.review_note:
                    raise Conflict("This scenario already has a saved approval with a different note.")
                receipt = json.loads(row["execution"])
            else:
                tests = [ProjectTest.model_validate(report[k]) for k in ("reference", "variant")]
                queued = self.runs._enqueue(db, project, tests)
                receipt = {"suite_id": queued["suite_id"], "runs": queued["ids"]}
                title = json.loads(row["draft"])["title"]
                db.execute("INSERT INTO project_named_suites VALUES(?,?)", (receipt["suite_id"], title))
                reviewed = {**report, "confirmed_at": utc_now(), "review_note": body.review_note}
                db.execute("UPDATE scenario_candidates SET execution=?,review=? WHERE id=?",
                           (canonical_json(receipt), canonical_json(reviewed), candidate_id))
            self.store._remember(db, scope, key, request, receipt)
        self.runs.wake.set()
        return receipt

    def dismiss(self, project_id, candidate_id, revision):
        with self.store.connection(True) as db:
            self._project(db, project_id, revision)
            row = self._candidate(db, project_id, candidate_id)
            if row["execution"]:
                raise Conflict("A completed review with linked runs stays in the project history.")
            db.execute("UPDATE scenario_candidates SET dismissed=1 WHERE id=?", (candidate_id,))
        return {"dismissed": True}

    def import_reference(self, project_id, body, key):
        scope, request = "scenario-import:" + project_id, body.model_dump()
        with self.store.connection(True) as db:
            previous = self.store._idempotent(db, scope, key, request)
            if previous:
                return previous
            project = self._project(db, project_id, body.expected_revision)
            asset, path = self.projects.asset_in_transaction(db, project_id, body.asset_id)
            if asset["kind"] != "requirements" or Path(asset["filename"]).suffix.lower() != ".json" or asset["size_bytes"] > 65536:
                raise HTTPException(422, "Choose a requirements JSON file up to 64 KiB.")
            try:
                with path.open("rb") as source:
                    raw = source.read(65537)
                if len(raw) > 65536:
                    raise Conflict("The reference size changed while being imported.")
                if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
                    raise Conflict("The reference changed while being imported.")
                ref = ReferenceFile.model_validate_json(raw)
                if ref.adapter not in {a["id"] for a in project_adapters(project)}:
                    raise ValueError("This reference model is unavailable for the selected project.")
                inputs = ref.inputs.copy()
                if ref.adapter == "structural_beam":
                    inputs.setdefault("kind", ref.adapter)
                model = MODELS[ref.adapter].model_validate(inputs)
            except Conflict:
                raise
            except (ValueError, RecursionError) as exc:
                detail = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
                raise HTTPException(422, "Invalid reference JSON: " + detail[:260]) from exc
            test = ProjectTest(label=ref.label or f"Reference from {asset['filename']}"[:120], adapter=ref.adapter,
                               inputs=model.model_dump(exclude_none=True))
            receipt = self.runs._enqueue(db, project, [test])
            db.execute("INSERT INTO scenario_imports VALUES(?,?,?)", (receipt["ids"][0], asset["id"], asset["sha256"]))
            self.store._remember(db, scope, key, request, receipt)
        self.runs.wake.set()
        return receipt


def scenario_router(service):
    router = APIRouter(prefix="/api/projects/{project_id}/scenarios", tags=["scenario discovery"])

    @router.get("")
    def history(project_id: str):
        return service.history(project_id)

    @router.post("/import-reference", status_code=202)
    def import_reference(project_id: str, body: ReferenceImport, idempotency_key: str | None = Header(None)):
        return service.import_reference(project_id, body, _key(idempotency_key))

    @router.post("/generate", status_code=202)
    def generate(project_id: str, body: Generate, idempotency_key: str | None = Header(None)):
        return service.generate(project_id, body, _key(idempotency_key))

    @router.get("/batches/{batch_id}/results")
    def batch_results(project_id: str, batch_id: str):
        return service.results(project_id, batch_id)

    @router.post("/batches/{batch_id}/execute-all", status_code=202)
    def execute_all(project_id: str, batch_id: str, body: Revision, idempotency_key: str | None = Header(None)):
        return service.execute_all(project_id, batch_id, body, _key(idempotency_key))

    @router.post("/{candidate_id}/preview")
    def preview(project_id: str, candidate_id: str, body: Review):
        return service.preview(project_id, candidate_id, body)

    @router.post("/{candidate_id}/execute", status_code=202)
    def execute(project_id: str, candidate_id: str, body: Execute, idempotency_key: str | None = Header(None)):
        return service.execute(project_id, candidate_id, body, _key(idempotency_key))

    @router.post("/{candidate_id}/dismiss")
    def dismiss(project_id: str, candidate_id: str, body: Revision):
        return service.dismiss(project_id, candidate_id, body.expected_revision)

    return router
