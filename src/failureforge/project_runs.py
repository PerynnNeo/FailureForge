"""Immutable project runs, durable suite scheduling and matched revision comparisons."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import Field

from .contracts import canonical_json, config_hash, utc_now
from .persistence import Conflict, new_id
from .project_bindings import binding_catalog, resolve_bindings
from .project_solver import adapters
from .project_validity import assessment_error
from .projects import IntakeModel, ProjectSpec, ProjectUpdate

TIMEOUT = 75
MAX_SUITE_TESTS = 16
SUMMARY = "id,label,adapter,project_revision,created_at,status,suite_id,attempt,error"


def _database_busy(error):
    # Extended SQLite result codes retain the primary code in their low byte.
    return (getattr(error, "sqlite_errorcode", 0) & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


class ProjectTest(IntakeModel):
    label: str = Field(min_length=1, max_length=120)
    adapter: str = Field(min_length=1, max_length=50)
    inputs: dict
    bindings: dict[Annotated[str, Field(min_length=1, max_length=80)],
                   Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=dict, max_length=32)


class Revision(IntakeModel):
    expected_revision: int = Field(strict=True, ge=1)


class Single(ProjectTest, Revision):
    pass


class Suite(Revision):
    tests: list[ProjectTest] = Field(min_length=1, max_length=MAX_SUITE_TESTS)
    label: str | None = Field(default=None, min_length=1, max_length=120)


def _suite_label(tests):
    return tests[0].label if len(tests) == 1 else f"{len(tests)}-case test suite"


def project_adapters(project):
    available = adapters(project["analysis_type"])
    if project.get("robot_source") == "supported" and project.get("robot_template") == "packaging_lift_v1":
        return available
    return [adapter for adapter in available if adapter["id"] != "packaging_lift"]


def outcome(record):
    if record["status"] != "completed" or assessment_error(record.get("result")):
        return None
    result = record["result"]
    return result.get("passed", result.get("summary", {}).get("validation_passed"))


def _joint_mapping(model):
    if not isinstance(model, dict) or not model.get("root_link") or not model.get("tip_link"):
        return None
    joints = model.get("joints")
    if not isinstance(joints, list) or not joints:
        return None
    mapping = {}
    for joint in joints:
        if not isinstance(joint, dict):
            return None
        fields = [joint.get(key) for key in ("name", "type", "unit", "parent", "child")]
        axis = joint.get("axis_in_joint_frame")
        if (not all(isinstance(value, str) and value for value in fields) or fields[0] in mapping
                or not isinstance(axis, list) or len(axis) != 3
                or not all(type(x) in (float, int) and math.isfinite(x) for x in axis)):
            return None
        follower = joint.get("mimic")
        if follower is not None:
            if (not isinstance(follower, dict) or not isinstance(follower.get("source"), str)
                    or not all(type(follower.get(k)) in (float, int) and math.isfinite(follower[k]) for k in ("multiplier", "offset"))):
                return None
            follower = (follower["source"], follower["multiplier"], follower["offset"])
        mapping[fields[0]] = (*fields[1:], tuple(axis), follower)
    return (model["root_link"], model["tip_link"], sorted(mapping.items()))


def compare(before, after):
    left, right = before["inputs"], after["inputs"]
    differences = {k: {"baseline": left.get(k), "candidate": right.get(k)} for k in sorted(left.keys() | right.keys())
                   if left.get(k) != right.get(k)}
    reasons = []
    if before["id"] == after["id"]:
        reasons.append("Choose two distinct executions")
    if before["status"] != "completed" or after["status"] != "completed":
        reasons.append("Both runs must have completed")
    for label, record in (("Baseline", before), ("Candidate", after)):
        invalid = assessment_error(record.get("result"))
        if invalid:
            reasons.append(f"{label} could not be assessed: {invalid}")
    if before["adapter"] != after["adapter"]:
        reasons.append("Adapter differs")
    if before["runtime"] != after["runtime"]:
        reasons.append("Solver implementation or runtime differs")
    old_bindings = before.get("definition", {}).get("bindings", {})
    new_bindings = after.get("definition", {}).get("bindings", {})
    changed_bindings = {field: {"baseline": old_bindings.get(field), "candidate": new_bindings.get(field)}
                        for field in sorted(old_bindings.keys() | new_bindings.keys())
                        if old_bindings.get(field, "").casefold() != new_bindings.get(field, "").casefold()}
    if changed_bindings:
        reasons.append("Parameter binding definition changed: " + ", ".join(changed_bindings))
    design_fields = {
        "structural_beam": {"width_m", "height_m", "length_m", "young_modulus_pa"},
        "thermal_rod": {"length_m", "area_m2", "conductivity_w_mk"},
        "robot_motion": {"model_asset_id", "controller_asset_id", "gain_per_s", "time_constant_s"},
        "joint_response": {"training_asset_id", "min_time_constant_s", "max_time_constant_s"},
        "cad_inventory": {"cad_asset_id", "bom_asset_id"},
    }.get(before["adapter"], set())
    for key in differences.keys() - design_fields:
        reasons.append(f"Test condition or acceptance rule changed: {key}")
    for key in ("analysis_type", "success_criteria"):
        if before["snapshot"][key] != after["snapshot"][key]:
            reasons.append(f"Project {key} changed")
    if before["adapter"] == after["adapter"] == "robot_motion":
        models = [r["result"].get("model", {}) if r["result"] else {} for r in (before, after)]
        baseline_mapping, candidate_mapping = map(_joint_mapping, models)
        if baseline_mapping is None or candidate_mapping is None:
            reasons.append("Robot joint mapping is incomplete in saved evidence")
        elif baseline_mapping != candidate_mapping:
            reasons.append("Robot joint mapping changed")
    deltas = {}
    if not reasons:
        a, b = [r["result"].get("summary", r["result"].get("metrics", {})) for r in (before, after)]
        deltas = {k: b[k] - a[k] for k in a.keys() & b.keys()
                  if type(a[k]) in (int, float) and type(b[k]) in (int, float)}
    a, b = outcome(before), outcome(after)
    classification = ("not_comparable" if reasons else "measurement_only" if a is None or b is None
                      else {(True, True): "unchanged_pass", (True, False): "new_failure",
                            (False, True): "resolved_failure", (False, False): "unchanged_failure"}[a, b])
    def ref(run):
        return {k: run[k] for k in ("id", "label", "project_revision", "adapter", "status", "evidence_hash")}
    return {"comparable": not reasons, "reasons": reasons, "baseline": ref(before), "candidate": ref(after),
            "outcome": classification, "metric_deltas": deltas, "changed_inputs": differences,
            "changed_bindings": changed_bindings}


class ProjectRuns:
    def __init__(self, projects):
        self.projects, self.store = projects, projects.store
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        with self.store.connection(True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS project_runs(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    project_revision INTEGER NOT NULL, suite_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    label TEXT NOT NULL, adapter TEXT NOT NULL, inputs TEXT NOT NULL, snapshot TEXT NOT NULL,
                    status TEXT NOT NULL, result TEXT, runtime TEXT, error TEXT, evidence_hash TEXT,
                    created_at TEXT NOT NULL, finished_at TEXT, lease TEXT, expires REAL, attempt INTEGER DEFAULT 0,
                    definition TEXT, binding_evidence TEXT, recheck_of TEXT, calibration_run_id TEXT);
                CREATE INDEX IF NOT EXISTS project_run_queue ON project_runs(status,created_at,ordinal);
                CREATE INDEX IF NOT EXISTS project_run_revision ON project_runs(project_id,project_revision,created_at);
                CREATE INDEX IF NOT EXISTS project_run_history ON project_runs(project_id,created_at);
                CREATE INDEX IF NOT EXISTS project_run_suite ON project_runs(project_id,suite_id,ordinal);
                CREATE TABLE IF NOT EXISTS project_named_suites(
                    suite_id TEXT PRIMARY KEY, label TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_crossed_designs(
                    suite_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    definition TEXT NOT NULL, created_at TEXT NOT NULL);""")
        # Serialize schema upgrades across concurrent service startups. Existing completed
        # rows retain the evidence hash captured by their original worker.
        with self.store.connection(True) as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(project_runs)")}
            for name in ("definition", "binding_evidence", "recheck_of", "calibration_run_id"):
                if name not in columns:
                    db.execute(f"ALTER TABLE project_runs ADD COLUMN {name} TEXT")

    def start(self):
        self.stop.clear()
        self.thread = threading.Thread(target=self._worker, daemon=True, name="project-analyses")
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(5)

    def submit(self, project_id, revision, tests, key, *, sweep=None, environment_matrix=None, crossed_design=None,
               explicit_suite=False, suite_label=None):
        # Empty bindings retain the original literal-only request hash for retries.
        definitions = [t.model_dump(exclude_defaults=True) for t in tests]
        request = {"revision": revision, "tests": definitions}
        if sweep is not None:
            request["sweep"] = sweep
        if environment_matrix is not None:
            request["environment_matrix"] = environment_matrix
        if crossed_design is not None:
            request["crossed_design"] = crossed_design
        if suite_label is not None:
            request["label"] = suite_label
        scope = f"project-analysis:{project_id}"
        if key is not None and not 8 <= len(key) <= 200:
            raise HTTPException(422, "Idempotency-Key must contain 8 to 200 characters")
        try:
            canonical_json(request)
        except (ValueError, RecursionError) as exc:
            raise HTTPException(422, "Analyses require finite, bounded JSON data") from exc
        with self.store.connection(True) as db:
            previous = self.store._idempotent(db, scope, key, request) if key else None
            if previous:
                if explicit_suite:
                    db.execute("INSERT OR IGNORE INTO project_named_suites VALUES(?,?)",
                               (previous["suite_id"], suite_label or _suite_label(tests)))
                return previous
            project = self.projects._get(db, project_id)
            if project["revision"] != revision:
                raise Conflict("Project changed. Reload before starting this analysis.")
            receipt = self._enqueue(db, project, tests, sweep=sweep)
            if explicit_suite:
                db.execute("INSERT INTO project_named_suites VALUES(?,?)",
                           (receipt["suite_id"], suite_label or _suite_label(tests)))
            if crossed_design is not None:
                db.execute("INSERT INTO project_crossed_designs VALUES(?,?,?,?)",
                           (receipt["suite_id"], project_id, canonical_json(crossed_design), utc_now()))
            if environment_matrix is not None:
                db.execute(
                    "INSERT INTO project_environment_matrices(suite_id, project_id, definition, created_at) "
                    "VALUES(?, ?, ?, ?)",
                    (receipt["suite_id"], project_id, canonical_json(environment_matrix), utc_now()),
                )
            if key:
                self.store._remember(db, scope, key, request, receipt)
        self.wake.set()
        return receipt

    def _enqueue(self, db, project, tests, *, sweep=None, previous_ids=(), calibration_id=None):
        allowed = {a["id"] for a in project_adapters(project)}
        if any(test.adapter not in allowed for test in tests):
            raise HTTPException(422, "Adapter is unavailable for the selected prototype and analysis type")
        suite_id, ids, now = new_id("suite"), [], utc_now()
        snapshot = canonical_json({k: v for k, v in project.items() if k != "readiness"})
        for ordinal, test in enumerate(tests):
            try:
                inputs, evidence = resolve_bindings(test, project)
            except ValueError as exc:
                raise HTTPException(422, f"{test.label}: {exc}") from exc
            run_id = new_id("run")
            ids.append(run_id)
            db.execute("""INSERT INTO project_runs(id,project_id,project_revision,suite_id,ordinal,label,adapter,
                       inputs,snapshot,status,created_at,definition,binding_evidence,recheck_of,calibration_run_id)
                       VALUES(?,?,?,?,?,?,?,?,?,'queued',?,?,?,?,?)""",
                       (run_id, project["id"], project["revision"], suite_id, ordinal, test.label, test.adapter,
                        canonical_json(inputs), snapshot, now, canonical_json(test.model_dump(exclude_defaults=True)),
                        canonical_json(evidence), previous_ids[ordinal] if previous_ids else None, calibration_id))
        if sweep is not None:
            db.execute("INSERT INTO project_sweeps(suite_id,project_id,definition,created_at) VALUES(?,?,?,?)",
                       (suite_id, project["id"], canonical_json(sweep), now))
        return {"suite_id": suite_id, "ids": ids}

    def get(self, project, run):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM project_runs WHERE project_id=? AND id=?", (project, run)).fetchone()
        if row is None:
            raise KeyError(run)
        result = dict(row)
        for key in ("inputs", "snapshot", "result", "runtime", "definition", "binding_evidence"):
            result[key] = json.loads(result[key]) if result[key] is not None else None
        if result["definition"] is None:
            result["definition"] = {k: result[k] for k in ("label", "adapter", "inputs")}
        result["binding_evidence"] = result["binding_evidence"] or {}
        result["assessment_error"] = assessment_error(result["result"])
        del result["lease"], result["expires"]
        return result

    def command(self, project, run, operation):
        with self.store.connection(True) as db:
            if operation == "cancel":
                sql = "UPDATE project_runs SET status='cancelled',lease=NULL,expires=NULL,finished_at=? WHERE project_id=? AND id=? AND status IN ('running','queued')"
            else:
                sql = "UPDATE project_runs SET status='queued',lease=NULL,expires=NULL,error=NULL,finished_at=? WHERE project_id=? AND id=? AND status='interrupted'"
            if not db.execute(sql, (utc_now() if operation == "cancel" else None, project, run)).rowcount:
                raise Conflict("The requested operation is unavailable for this run")
        self.wake.set()
        return self.get(project, run)

    def _claim(self):
        with self.store.connection(True) as db:
            self._recover_expired(db)
            row = db.execute("SELECT * FROM project_runs WHERE status='queued' ORDER BY created_at,ordinal LIMIT 1").fetchone()
            if row is None:
                return None
            lease = new_id("lease")
            db.execute("""UPDATE project_runs SET status='running',lease=?,expires=?,attempt=attempt+1
                          WHERE id=?""", (lease, time.time()+TIMEOUT+15, row["id"]))
        return dict(row), lease

    @staticmethod
    def _recover_expired(db):
        db.execute("""UPDATE project_runs SET status='interrupted',error='Execution lease expired',
                      finished_at=?,lease=NULL,expires=NULL WHERE status='running' AND expires<=?""",
                   (utc_now(), time.time()))

    def _retry_busy(self, operation, *args):
        while True:
            try:
                return operation(*args)
            except sqlite3.OperationalError as exc:
                if not _database_busy(exc):
                    raise
                if self.stop.wait(0.2):
                    return None

    def _publish(self, row, lease, response):
        result, runtime = response.get("result"), response.get("runtime")
        evidence = {"snapshot": json.loads(row["snapshot"]), "inputs": json.loads(row["inputs"]),
                    "adapter": row["adapter"], "runtime": runtime, "result": result}
        bindings = json.loads(row["binding_evidence"] or "{}")
        if bindings:
            evidence.update(definition=json.loads(row["definition"]), binding_evidence=bindings)
        identity = config_hash(evidence) if result else None
        with self.store.connection(True) as db:
            # Evaluate wall time after the write lock is acquired. A stalled worker
            # must not publish just because nobody has scanned expired leases yet.
            updated = db.execute("""UPDATE project_runs SET status=?,result=?,runtime=?,error=?,evidence_hash=?,finished_at=?,
                                  lease=NULL,expires=NULL WHERE id=? AND lease=? AND status='running' AND expires>?""",
                                 (response["status"], canonical_json(result), canonical_json(runtime), response.get("error"),
                                  identity, utc_now(), row["id"], lease, time.time()))
            if not updated.rowcount:
                self._recover_expired(db)

    def _worker(self):
        while not self.stop.is_set():
            job = self._retry_busy(self._claim)
            if job is None:
                self.wake.wait(0.5)
                self.wake.clear()
                continue
            row, lease = job
            try:
                response = self._execute(row, lease)
            except Exception as exc:
                response = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:2000]}
            self._retry_busy(self._publish, row, lease, response)

    def _execute(self, row, lease):
        snapshot = json.loads(row["snapshot"])
        job = {"adapter": row["adapter"], "inputs": json.loads(row["inputs"]), "analysis_type": snapshot["analysis_type"],
               "assets": {a["id"]: {**a, "path": str(self.projects.asset_path(a["id"]))} for a in snapshot["assets"]}}
        with tempfile.TemporaryDirectory(prefix="failureforge-solver-") as directory:
            root = Path(directory)
            jobfile, output = root/"job.json", root/"result.json"
            jobfile.write_text(canonical_json(job), encoding="utf-8")
            env = {**os.environ, "FAILUREFORGE_SOLVER_OUTPUT": str(output), "OPENBLAS_NUM_THREADS": "1",
                   "OMP_NUM_THREADS": "1", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
            with jobfile.open("rb") as source, (root/"errors").open("wb") as errors, subprocess.Popen(
                    [sys.executable, "-m", "failureforge.project_solver"], cwd=root, stdin=source,
                    stdout=errors, stderr=errors, env=env) as process:
                deadline = time.monotonic() + TIMEOUT
                try:
                    while process.poll() is None:
                        if self.stop.wait(0.15):
                            return {"status": "interrupted", "error": "Service stopped during execution"}
                        if time.monotonic() >= deadline:
                            return {"status": "error", "error": "Solver exceeded its wall-time allowance"}
                        try:
                            with self.store.connection() as db:
                                if not db.execute("SELECT 1 FROM project_runs WHERE id=? AND lease=? AND expires>?",
                                                  (row["id"], lease, time.time())).fetchone():
                                    return {"status": "cancelled"}
                        except sqlite3.OperationalError as exc:
                            if not _database_busy(exc):
                                raise
                            # A transient read lock does not establish cancellation.
                            # The deadline still applies; publication rechecks the lease.
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                if process.returncode or not output.is_file():
                    return {"status": "error", "error": f"Solver process failed (exit {process.returncode})"}
            return json.loads(output.read_text(encoding="utf-8"))

    @staticmethod
    def _dependent_checks(db, project, revision, parameter):
        rows = db.execute("""SELECT id,definition FROM project_runs WHERE project_id=? AND project_revision=?
                             AND json_type(definition,'$.bindings')='object' ORDER BY created_at DESC,rowid DESC""",
                          (project, revision))
        tests, previous_ids, seen = [], [], set()
        for row in rows:
            definition = json.loads(row["definition"])
            bindings = {field: name.casefold() for field, name in definition["bindings"].items()}
            if parameter.casefold() not in bindings.values():
                continue
            # Repeated submissions with another display label still describe the same check.
            identity = (definition["adapter"], canonical_json(definition["inputs"]), canonical_json(bindings))
            if identity in seen:
                continue
            if len(tests) == MAX_SUITE_TESTS:
                return tests, previous_ids, True
            seen.add(identity)
            tests.append(ProjectTest.model_validate(definition))
            previous_ids.append(row["id"])
        return tests, previous_ids, False

    def promote(self, project, run, revision):
        record = self.get(project, run)
        if outcome(record) is not True or record["adapter"] not in ("calibration", "joint_response"):
            raise Conflict("A passing held-out calibration is required")
        if record["project_revision"] != revision:
            raise Conflict("Calibration belongs to a different project revision; rerun against the current revision")
        result = record["result"]
        if record["adapter"] == "joint_response":
            parameter = result["parameter"]
        else:
            summary = result["summary"]
            if summary["at_parameter_bound"] or any(r["run_id"].startswith("example-") for r in result["fit"] + result["validation"]):
                raise Conflict("Promotion requires independent measurement records and a resolved fit inside the bounds")
            parameter = {"name": summary["parameter"], "value": summary["fitted_value"],
                         "unit": "Pa" if summary["parameter"] == "young_modulus_pa" else "W/(m·K)"}
        new = {**parameter, "value": str(parameter["value"]), "source": "calibrated",
               "evidence": f"Validated analysis {run}, evidence {record['evidence_hash']}"}
        with self.store.connection(True) as db:
            current = self.projects._get(db, project)
            if current["revision"] != revision:
                raise Conflict("Project changed since calibration. Rerun the calibration on the current revision.")
            tests, previous_ids, more = self._dependent_checks(db, project, revision, new["name"])
            data = {k: current[k] for k in ProjectSpec.model_fields}
            data["parameters"] = [p for p in data["parameters"] if p["name"].casefold() != new["name"].casefold()] + [new]
            try:
                spec = ProjectUpdate(**data, expected_revision=revision)
            except ValueError as exc:
                raise HTTPException(422, f"Calibration could not be saved: {exc}") from exc
            saved = self.projects.update_in_transaction(db, project, spec, f"Promoted calibration {run}")
            queued = (self._enqueue(db, saved, tests, previous_ids=previous_ids, calibration_id=run)
                      if tests else {"suite_id": None, "ids": []})
        if tests:
            self.wake.set()
        return {**saved, "rechecks": {"suite_id": queued["suite_id"], "run_ids": queued["ids"],
                                     "previous_run_ids": previous_ids, "more_available": more}}


def analysis_router(runs):
    from .project_replay_pair import replay_pair

    router = APIRouter(prefix="/api/projects/{project}", tags=["project analyses"])

    @router.get("/replay-pair")
    def preferred_replay(project: str):
        with runs.store.connection() as db:
            runs.store._required(db, "projects", project)
            return replay_pair(db, project)

    @router.get("/analysis")
    def history(project: str):
        record = runs.projects.get(project)
        catalog = [{**a, **binding_catalog(a["id"], record["analysis_type"])} for a in project_adapters(record)]
        with runs.store.connection() as db:
            rows = db.execute(f"""SELECT {SUMMARY},
                    CASE WHEN json_extract(result,'$.model.reference_id')='two_finger_hand_v1'
                         AND coalesce(json_extract(snapshot,'$.robot_template'),'')!='two_finger_hand_v1'
                         THEN 1 ELSE 0 END AS reference_example
                    FROM project_runs WHERE project_id=? ORDER BY created_at DESC,ordinal LIMIT 200""", (project,))
            return {"adapters": catalog, "runs": [dict(r) for r in rows]}

    @router.post("/analysis", status_code=202)
    def run_single(project: str, spec: Single, idempotency_key: str | None = Header(None)):
        result = runs.submit(project, spec.expected_revision, [ProjectTest(**spec.model_dump(exclude={"expected_revision"}))], idempotency_key)
        return runs.get(project, result["ids"][0])

    @router.post("/analysis-suite", status_code=202)
    def run_suite(project: str, spec: Suite, idempotency_key: str | None = Header(None)):
        result = runs.submit(project, spec.expected_revision, spec.tests, idempotency_key,
                             explicit_suite=True, suite_label=spec.label)
        return {"suite_id": result["suite_id"], "runs": [runs.get(project, i) for i in result["ids"]]}

    @router.get("/analysis-suite/{suite_id}")
    def suite_detail(project: str, suite_id: str):
        with runs.store.connection() as db:
            ids = [r["id"] for r in db.execute(
                "SELECT id FROM project_runs WHERE project_id=? AND suite_id=? ORDER BY ordinal",
                (project, suite_id))]
        if not ids:
            raise KeyError(suite_id)
        return {"suite_id": suite_id, "runs": [runs.get(project, i) for i in ids]}

    @router.get("/analysis/{run}")
    def detail(project: str, run: str):
        return runs.get(project, run)

    @router.get("/analysis/{run}/compare/{other}")
    def compare_runs(project: str, run: str, other: str):
        return compare(runs.get(project, run), runs.get(project, other))

    @router.post("/analysis/{run}/promote")
    def promote(project: str, run: str, spec: Revision):
        return runs.promote(project, run, spec.expected_revision)

    @router.post("/analysis/{run}/cancel")
    def cancel(project: str, run: str):
        return runs.command(project, run, "cancel")

    @router.post("/analysis/{run}/resume")
    def resume(project: str, run: str):
        return runs.command(project, run, "resume")
    return router
