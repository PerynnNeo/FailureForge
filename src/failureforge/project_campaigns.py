"""Index real project batches while keeping one immutable copy of each execution."""
import json

from fastapi import APIRouter, Header, HTTPException, Query

from .campaign_coverage import campaign_coverage, factor_catalog, flatten_controls
from .crossed_inputs import CrossedCampaign, crossed_coordinates, crossed_design, crossed_tests
from .project_runs import outcome, project_adapters
from .project_validity import assessment_error
from .project_sweeps import _summarize
from .environment_matrices import LiftCondition, _report


# Legacy single-run submissions also received a suite_id. Only explicit suites,
# recorded sweep/matrix definitions, and legacy multi-run groups belong here.
def _batches(*, filtered=False):
    where = "WHERE r.project_id=:project AND r.suite_id=:suite" if filtered else ""
    crossed_filter = "AND c.project_id=:project AND c.suite_id=:suite" if filtered else ""
    return f"""
        SELECT r.suite_id, r.project_id, json_extract(p.spec,'$.name') project_name,
               min(r.project_revision) project_revision, min(r.created_at) created_at,
               CASE WHEN m.suite_id IS NOT NULL THEN 'matrix'
                    WHEN s.suite_id IS NOT NULL THEN 'sweep' ELSE 'suite' END kind,
               coalesce(json_extract(m.definition,'$.label'), json_extract(s.definition,'$.label'),
                        n.label, count(*) || '-case test suite') label,
               coalesce(json_array_length(c.definition,'$.axes[0].values') * json_array_length(c.definition,'$.axes[1].values'),count(*)) total,
               sum(r.status='completed') completed,
               CASE WHEN sum(r.status IN ('queued','running'))>0 THEN 'running'
                    WHEN sum(r.status!='completed')>0 OR
                         count(*) < json_array_length(c.definition,'$.axes[0].values') * json_array_length(c.definition,'$.axes[1].values')
                    THEN 'partial' ELSE 'completed' END status
          FROM project_runs r JOIN projects p ON p.id=r.project_id
          LEFT JOIN project_environment_matrices m ON m.suite_id=r.suite_id
          LEFT JOIN project_sweeps s ON s.suite_id=r.suite_id
          LEFT JOIN project_named_suites n ON n.suite_id=r.suite_id
          LEFT JOIN project_crossed_designs c ON c.suite_id=r.suite_id
          {where}
          GROUP BY r.project_id,r.suite_id
          HAVING count(*)>1 OR m.suite_id IS NOT NULL OR s.suite_id IS NOT NULL OR n.suite_id IS NOT NULL
          UNION ALL
          SELECT c.suite_id,c.project_id,json_extract(p.spec,'$.name'),json_extract(c.definition,'$.expected_revision'),
                 c.created_at,'suite',json_extract(c.definition,'$.label'),
                 json_array_length(c.definition,'$.axes[0].values') * json_array_length(c.definition,'$.axes[1].values'),0,'partial'
            FROM project_crossed_designs c JOIN projects p ON p.id=c.project_id
           WHERE NOT EXISTS (SELECT 1 FROM project_runs r WHERE r.project_id=c.project_id AND r.suite_id=c.suite_id)
           {crossed_filter}
    """


def _campaign_records(db, project, suite_id, *, coverage=False):
    key = (project, suite_id)
    meta = db.execute(_batches(filtered=True), {"project": project, "suite": suite_id}).fetchone()
    if meta is None:
        raise HTTPException(404, "Unknown project campaign")
    extras = """ ,project_revision, json_extract(snapshot,'$.operating_factors') declared,
        json_extract(definition,'$.bindings') bindings,
        CASE WHEN adapter IN ('thermal_rod','structural_beam') THEN json_extract(result,'$.inputs') END effective,
        json_extract(result,'$.model.joints') joints""" if coverage else ""
    rows = db.execute(f"""SELECT id,label,adapter,ordinal,status,error,runtime,inputs,evidence_hash,
                   json_extract(result,'$.passed') passed,
                   coalesce(json_extract(result,'$.summary'),json_extract(result,'$.metrics')) metrics,
                   json_extract(result,'$.numerical_diagnostics.passed') diagnostics_passed,
                   json_extract(result,'$.dynamics.reference_qualification') qualification {extras}
                FROM project_runs WHERE project_id=? AND suite_id=? ORDER BY ordinal""", key).fetchall()
    report = None
    if meta["kind"] == "matrix":
        definition = db.execute("SELECT definition FROM project_environment_matrices WHERE project_id=? AND suite_id=?", key).fetchone()
        report = _report(project, {**dict(meta), **json.loads(definition[0])}, rows)
    elif meta["kind"] == "sweep":
        definition = json.loads(db.execute("SELECT definition FROM project_sweeps WHERE project_id=? AND suite_id=?", key).fetchone()[0])
        by_ordinal = {r["ordinal"]: r for r in rows}
        missing = {"id": None, "status": "missing", "error": "Missing run for this planned condition", "metrics": None}
        report = _summarize(suite_id, definition, [by_ordinal.get(index, missing) for index in range(len(definition["values"]))])
    else:
        plan = db.execute("SELECT definition FROM project_crossed_designs WHERE project_id=? AND suite_id=?", key).fetchone()
        if plan:
            design = json.loads(plan["definition"])
            saved = db.execute("SELECT json_extract(snapshot,'$.operating_factors') FROM project_revisions WHERE project_id=? AND revision=?",
                               (project, design["expected_revision"])).fetchone()
            report = _crossed_report(rows, design)
            report["declared"] = json.loads(saved[0] or "[]") if saved else []
    return dict(meta), rows, report


def _result(row, verdict):
    result = {"summary": json.loads(row["metrics"] or "{}"),
              "numerical_diagnostics": {"passed": row["diagnostics_passed"] != 0},
              "dynamics": {"reference_qualification": json.loads(row["qualification"] or "[]")}}
    if row["passed"] is not None:
        result["passed"] = bool(row["passed"])
    error = verdict.get("error") or row["error"] or assessment_error(result)
    passed = verdict["passed"] if verdict else outcome({"result": result, "status": row["status"]})
    return result["summary"], error, passed if not error else None


def _crossed_report(rows, design):
    by_ordinal = {row["ordinal"]: row for row in rows}
    cells = []
    for ordinal, coordinate in enumerate(crossed_coordinates(design["axes"], design["reference"])):
        row = by_ordinal.get(ordinal)
        error, passed = "Missing run for this planned condition", None
        if row is not None:
            _, error, passed = _result(row, {})
            inputs = flatten_controls(json.loads(row["inputs"]))
            if row["adapter"] != design["adapter"] or any(inputs.get(k) != v for k, v in coordinate.items()):
                error, passed = "Saved run inputs differ from the planned condition", None
        cells.append({**coordinate, "reference": coordinate == design["reference"], "error": error,
                      "passed": passed, "run_id": row["id"] if row else None})
    return {"adapter": design["adapter"], "cells": cells, "crossed_design": design}


def _coverage(meta, rows, report):
    planned = (report or {}).get("cells", (report or {}).get("points", []))
    assessed = {point["run_id"]: point for point in planned}
    axes = None
    if meta["kind"] == "sweep":
        axes = [report["field"]]
    elif meta["kind"] == "matrix":
        axes = list(LiftCondition.model_fields)
    elif (report or {}).get("crossed_design"):
        axes = [axis["field"] for axis in report["crossed_design"]["axes"]]

    def coordinates(point):
        if not point:
            return {}
        if meta["kind"] == "sweep":
            return {report["field"]: point["value"]}
        return {field: point[field] for field in axes}

    records = []
    for row in rows:
        verdict = assessed.get(row["id"], {})
        _, error, passed = _result(row, verdict)
        inputs = flatten_controls(json.loads(row["effective"] or row["inputs"]))
        if meta["kind"] == "sweep" and inputs.get(report["field"]) != verdict.get("value"):
            error = "Saved run inputs differ from the planned condition"
        if row["status"] in ("queued", "running") and not error:
            category = "pending"
        elif (row["status"] != "completed" or error or not row["evidence_hash"]
              or row["runtime"] in (None, "", "null")):
            category = "blocked"
        else:
            category = "measurement_only" if passed is None else "passed" if passed else "failed"
        records.append({"id": row["id"], "adapter": row["adapter"], "revision": row["project_revision"],
                        "runtime": row["runtime"], "controls": inputs, "category": category, "bindings": row["bindings"],
                        "joints": json.loads(row["joints"] or "[]"),
                        "planned_coordinates": coordinates(verdict)})
    for point in planned:
        if point["run_id"] is None:
            records.append({"id": None, "adapter": report["adapter"], "controls": coordinates(point), "category": "blocked"})
    declared = (report or {}).get("declared") if not rows else json.loads(rows[0]["declared"] or "[]")
    return campaign_coverage(meta, records, declared or [], axes)


def _phase_review(db, project, suite_id, revision):
    row = db.execute(
        """SELECT p.revision, json_extract(p.spec,'$.task_phases') current_phases,
                  json_extract(h.snapshot,'$.task_phases') campaign_phases
           FROM projects p LEFT JOIN project_revisions h ON h.project_id=p.id AND h.revision=?
           WHERE p.id=?""", (revision, project)).fetchone()
    submission = db.execute(
        """SELECT phase_id,condition_id FROM project_phase_tests
           WHERE project_id=? AND suite_id=? AND project_revision=?""",
        (project, suite_id, revision)).fetchone()
    return {"current_revision": row["revision"], "current_phases": json.loads(row["current_phases"] or "[]"),
            "campaign_revision": revision, "campaign_phases": json.loads(row["campaign_phases"]) if row["campaign_phases"] else None,
            "submitted_condition": dict(submission) if submission else None}


def campaign_router(runs):
    router = APIRouter(prefix="/api/project-campaigns", tags=["project campaigns"])

    @router.get("")
    def list_batches(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
        with runs.store.connection() as db:
            db.execute("BEGIN")
            statement = _batches()
            total = db.execute(f"SELECT count(*) FROM ({statement})").fetchone()[0]
            rows = db.execute(f"SELECT * FROM ({statement}) ORDER BY created_at DESC,suite_id LIMIT ? OFFSET ?", (limit, offset))
            return {"items": [dict(row) for row in rows], "total": total}

    @router.get("/{project}/{suite_id}")
    def batch(project: str, suite_id: str):
        with runs.store.connection() as db:
            db.execute("BEGIN")
            meta, rows, report = _campaign_records(db, project, suite_id)

        assessed = {p["run_id"]: p for p in (report or {}).get("cells", (report or {}).get("points", []))}
        inputs = [flatten_controls(json.loads(r["inputs"])) for r in rows]
        varied = sorted(k for k in set().union(*inputs)
                        if any(item.get(k) != inputs[0].get(k) for item in inputs[1:]))
        conditions = []
        for row, values in zip(rows, inputs, strict=True):
            verdict = assessed.get(row["id"], {})
            metrics, error, passed = _result(row, verdict)
            coordinates = {k: verdict[k] for k in ("payload_kg", "head_force_n", "value") if k in verdict}
            if (report or {}).get("crossed_design"):
                coordinates = {axis["field"]: verdict[axis["field"]] for axis in report["crossed_design"]["axes"]}
            elif report is None:
                coordinates = {k: values[k] for k in varied if k in values}
            conditions.append({**{k: row[k] for k in ("id", "label", "adapter", "status")}, "error": error,
                               "passed": passed, "reference": verdict.get("reference", False),
                               "coordinates": coordinates, "metrics": metrics})
        return {**dict(meta), "runs": conditions, "field": (report or {}).get("field"),
                "crossed_design": (report or {}).get("crossed_design")}

    @router.get("/{project}/coverage/catalog")
    def project_factors(project: str):
        return factor_catalog(project_adapters(runs.projects.get(project)))

    @router.get("/{project}/{suite_id}/coverage")
    def coverage(project: str, suite_id: str):
        with runs.store.connection() as db:
            db.execute("BEGIN")
            meta, rows, report = _campaign_records(db, project, suite_id, coverage=True)
            phases = _phase_review(db, project, suite_id, meta["project_revision"])
        return {**_coverage(meta, rows, report), "phase_review": phases}

    @router.post("/{project}/crossed", status_code=202)
    def submit_crossed(project: str, spec: CrossedCampaign, idempotency_key: str | None = Header(None)):
        with runs.store.connection() as db:
            runs.store._required(db, "projects", project)
            saved = db.execute("SELECT snapshot FROM project_revisions WHERE project_id=? AND revision=?",
                               (project, spec.expected_revision)).fetchone()
        if saved is None:
            raise HTTPException(409, "Unknown project revision")
        try:
            tests = crossed_tests(spec, json.loads(saved["snapshot"]))
        except (ValueError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return runs.submit(project, spec.expected_revision, tests, idempotency_key,
                           explicit_suite=True, suite_label=spec.label, crossed_design=crossed_design(spec))

    return router
