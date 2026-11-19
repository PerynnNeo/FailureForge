"""Index real project batches while keeping one immutable copy of each execution."""
import json

from fastapi import APIRouter, HTTPException, Query

from .project_runs import outcome
from .project_validity import assessment_error
from .project_sweeps import _summarize
from .environment_matrices import _report


# Legacy single-run submissions also received a suite_id. Only explicit suites,
# recorded sweep/matrix definitions, and legacy multi-run groups belong here.
def _batches(where=""):
    return f"""
        SELECT r.suite_id, r.project_id, json_extract(p.spec,'$.name') project_name,
               min(r.project_revision) project_revision, min(r.created_at) created_at,
               CASE WHEN m.suite_id IS NOT NULL THEN 'matrix'
                    WHEN s.suite_id IS NOT NULL THEN 'sweep' ELSE 'suite' END kind,
               coalesce(json_extract(m.definition,'$.label'), json_extract(s.definition,'$.label'),
                        n.label, count(*) || '-case test suite') label,
               count(*) total, sum(r.status='completed') completed,
               CASE WHEN sum(r.status IN ('queued','running'))>0 THEN 'running'
                    WHEN sum(r.status!='completed')>0 THEN 'partial' ELSE 'completed' END status
          FROM project_runs r JOIN projects p ON p.id=r.project_id
          LEFT JOIN project_environment_matrices m ON m.suite_id=r.suite_id
          LEFT JOIN project_sweeps s ON s.suite_id=r.suite_id
          LEFT JOIN project_named_suites n ON n.suite_id=r.suite_id
          {where}
          GROUP BY r.project_id,r.suite_id
          HAVING count(*)>1 OR m.suite_id IS NOT NULL OR s.suite_id IS NOT NULL OR n.suite_id IS NOT NULL
    """


def campaign_router(runs):
    router = APIRouter(prefix="/api/project-campaigns", tags=["project campaigns"])

    @router.get("")
    def list_batches(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
        with runs.store.connection() as db:
            db.execute("BEGIN")
            statement = _batches()
            total = db.execute(f"SELECT count(*) FROM ({statement})").fetchone()[0]
            rows = db.execute(statement + " ORDER BY created_at DESC,r.suite_id LIMIT ? OFFSET ?", (limit, offset))
            return {"items": [dict(row) for row in rows], "total": total}

    @router.get("/{project}/{suite_id}")
    def batch(project: str, suite_id: str):
        with runs.store.connection() as db:
            db.execute("BEGIN")
            key = (project, suite_id)
            meta = db.execute(_batches("WHERE r.project_id=? AND r.suite_id=?"), key).fetchone()
            if meta is None:
                raise HTTPException(404, "Unknown project campaign")
            rows = db.execute("""SELECT id,label,adapter,ordinal,status,error,runtime,inputs,evidence_hash,
                       json_extract(result,'$.passed') passed,
                       coalesce(json_extract(result,'$.summary'),json_extract(result,'$.metrics')) metrics,
                       json_extract(result,'$.numerical_diagnostics.passed') diagnostics_passed,
                       json_extract(result,'$.dynamics.reference_qualification') qualification
                    FROM project_runs WHERE project_id=? AND suite_id=? ORDER BY ordinal""", key).fetchall()
            report = None
            if meta["kind"] == "matrix":
                definition = db.execute("SELECT definition FROM project_environment_matrices WHERE project_id=? AND suite_id=?", key).fetchone()
                report = _report(project, {**dict(meta), **json.loads(definition[0])}, rows)
            elif meta["kind"] == "sweep":
                definition = db.execute("SELECT definition FROM project_sweeps WHERE project_id=? AND suite_id=?", key).fetchone()
                report = _summarize(suite_id, json.loads(definition[0]), rows)

        assessed = {p["run_id"]: p for p in (report or {}).get("cells", (report or {}).get("points", []))}
        inputs = [json.loads(r["inputs"]) for r in rows]
        varied = sorted(k for k in set().union(*inputs)
                        if any(item.get(k) != inputs[0].get(k) for item in inputs[1:]))
        conditions = []
        for row, values in zip(rows, inputs, strict=True):
            result = {"summary": json.loads(row["metrics"] or "{}"),
                      "numerical_diagnostics": {"passed": row["diagnostics_passed"] != 0},
                      "dynamics": {"reference_qualification": json.loads(row["qualification"] or "[]")}}
            if row["passed"] is not None:
                result["passed"] = bool(row["passed"])
            verdict = assessed.get(row["id"], {})
            error = verdict.get("error") or row["error"] or assessment_error(result)
            passed = verdict["passed"] if verdict else outcome({"result": result, "status": row["status"]})
            coordinates = {k: verdict[k] for k in ("payload_kg", "head_force_n", "value") if k in verdict}
            if report is None:
                coordinates = {k: values[k] for k in varied if k in values}
            conditions.append({**{k: row[k] for k in ("id", "label", "adapter", "status")}, "error": error,
                               "passed": passed if not error else None, "reference": verdict.get("reference", False),
                               "coordinates": coordinates, "metrics": result["summary"]})
        return {**dict(meta), "runs": conditions, "field": (report or {}).get("field")}
    return router
