"""Project sweeps evaluate one declared coordinate at finite grid points, including its reference."""
from __future__ import annotations

import json
import math
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import Field, FiniteFloat

from .project_bindings import FIELD_UNITS, resolve_bindings
from .project_runs import ProjectTest
from .project_solver import MODELS
from .projects import IntakeModel


FIELDS = {
    "structural_beam": {"length_m": "Beam length", "width_m": "Beam width", "height_m": "Beam height",
                        "young_modulus_pa": "Young's modulus", "tip_force_n": "Tip force",
                        "distributed_load_n_per_m": "Distributed load", "face_pressure_pa": "Uniform face pressure"},
    "thermal_rod": {"length_m": "Rod length", "area_m2": "Cross-sectional area", "conductivity_w_mk": "Conductivity",
                    "left_temperature_k": "Left boundary temperature", "right_temperature_k": "Right boundary temperature",
                    "heat_generation_w_m3": "Volumetric heat generation",
                    "right_ambient_temperature_k": "Right ambient temperature",
                    "right_film_coefficient_w_m2k": "Right end film coefficient"},
    "robot_motion": {"targets.*": "Joint target"},
}
ADAPTERS = {"structural": "structural_beam", "thermal": "thermal_rod", "robot_behavior": "robot_motion"}
MAX_POINTS = 16


class Sweep(IntakeModel):
    expected_revision: int = Field(strict=True, ge=1)
    adapter: Literal["structural_beam", "thermal_rod", "robot_motion"]
    label: str = Field(min_length=1, max_length=100)
    inputs: dict
    bindings: dict[Annotated[str, Field(min_length=1, max_length=80)], Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=dict, max_length=32)
    field: str = Field(min_length=1, max_length=108)
    values: list[Annotated[FiniteFloat, Field(strict=True)]] = Field(min_length=2, max_length=MAX_POINTS)


def _catalog(analysis):
    adapter = ADAPTERS[analysis]
    fields = [{"field": field, "label": label, "unit": FIELD_UNITS[adapter].get(field, "joint units")}
              for field, label in FIELDS[adapter].items()]
    return {"adapters": {adapter: fields}, "max_points": MAX_POINTS}


def _plan(spec, snapshot):
    if spec.adapter != ADAPTERS[snapshot["analysis_type"]]:
        raise ValueError("Sweep adapter is unavailable for this project")
    if any(a >= b for a, b in zip(spec.values, spec.values[1:])):
        raise ValueError("Grid values must increase strictly")
    joint = None
    if spec.adapter == "robot_motion":
        if not spec.field.startswith("targets.") or not isinstance(spec.inputs.get("targets"), dict):
            raise ValueError("Choose an existing numeric targets.<joint> field")
        joint = spec.field[len("targets."):]
        reference = spec.inputs["targets"].get(joint)
    else:
        if spec.field not in FIELDS[spec.adapter]:
            raise ValueError("Only catalog-listed physical inputs may vary")
        reference = spec.inputs.get(spec.field)
    if spec.field in spec.bindings:
        raise ValueError("The varied field requires a literal reference value")
    if type(reference) not in (int, float) or not math.isfinite(reference) or reference not in spec.values:
        raise ValueError("The grid must include the selected field's numeric reference in the base inputs")
    tests = []
    for ordinal, value in enumerate(spec.values, start=1):
        inputs = dict(spec.inputs)
        if joint is None:
            inputs[spec.field] = value
        else:
            inputs["targets"] = {**spec.inputs["targets"], joint: value}
        role = "reference" if value == reference else "point"
        test = ProjectTest(label=f"{spec.label} · {role} {ordinal}", adapter=spec.adapter, inputs=inputs, bindings=spec.bindings)
        # Validate all points before reserving any jobs. The worker assesses model-dependent feasibility.
        resolved, _ = resolve_bindings(test, snapshot)
        if spec.adapter != "robot_motion":
            resolved.setdefault("kind", spec.adapter)
        MODELS[spec.adapter].model_validate(resolved)
        tests.append(test)
    definition = {"label": spec.label, "adapter": spec.adapter, "field": spec.field,
                  "reference_value": reference, "values": spec.values, "project_revision": spec.expected_revision}
    return definition, tests


def _summarize(suite_id, definition, rows):
    reference = definition["reference_value"]
    if len(rows) != len(definition["values"]):
        raise RuntimeError("Stored sweep membership is incomplete")
    points, counts = [], dict.fromkeys(("measured", "passed", "failed", "pending", "blocked", "measurement_only"), 0)
    counts["total"] = len(rows)
    reference_row = rows[definition["values"].index(reference)]
    reference_runtime = reference_row["runtime"] if reference_row["status"] == "completed" else None
    for value, row in zip(definition["values"], rows, strict=True):
        status, error, passed = row["status"], row["error"], None
        metrics = json.loads(row["metrics"]) if row["metrics"] is not None else {}
        if status in ("queued", "running"):
            counts["pending"] += 1
        elif status != "completed":
            counts["blocked"] += 1
        else:
            counts["measured"] += 1
            if reference_runtime is not None and reference_runtime != row["runtime"]:
                error = "Solver runtime differs from the completed reference"
            elif row["diagnostics_passed"] == 0 or metrics.get("within_small_deflection_screen") is False:
                error = "Solver diagnostics or applicability checks failed"
            elif row["qualification"] is not None and any(not check["passed"] for check in json.loads(row["qualification"])):
                error = "Robot reference qualification failed"
            if error:
                counts["blocked"] += 1
            else:
                passed = bool(row["passed"]) if row["passed"] is not None else None
                category = "measurement_only" if passed is None else "passed" if passed else "failed"
                counts[category] += 1
        points.append({"value": value, "reference": value == reference, "run_id": row["id"], "status": status,
                       "passed": passed, "metrics": metrics, "error": error})
    nearest = min((p for p in points if p["passed"] is False), key=lambda p: abs(p["value"] - reference), default=None)
    ref = next(p for p in points if p["reference"])
    status = "running" if counts["pending"] else "partial" if counts["blocked"] else "completed"
    return {**definition, "suite_id": suite_id, "status": status, "points": points, "counts": counts,
            "reference_passed": ref["passed"], "nearest_observed_failure": nearest}


def sweep_router(runs):
    router = APIRouter(prefix="/api/projects/{project}/sweeps", tags=["project sweeps"])
    with runs.store.connection(True) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS project_sweeps (
            suite_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            definition TEXT NOT NULL, created_at TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS project_sweeps_history ON project_sweeps(project_id,created_at)")

    @router.get("/catalog")
    def catalog(project: str):
        return _catalog(runs.projects.get(project)["analysis_type"])

    @router.get("")
    def history(project: str):
        with runs.store.connection() as db:
            runs.store._required(db, "projects", project)
            rows = db.execute("SELECT suite_id,created_at,definition FROM project_sweeps WHERE project_id=? ORDER BY created_at DESC LIMIT 200", (project,)).fetchall()
        return {"sweeps": [dict(json.loads(r["definition"]), suite_id=r["suite_id"], created_at=r["created_at"]) for r in rows]}

    @router.get("/{suite_id}")
    def detail(project: str, suite_id: str):
        with runs.store.connection() as db:
            db.execute("BEGIN")
            sweep = db.execute("SELECT definition FROM project_sweeps WHERE project_id=? AND suite_id=?", (project, suite_id)).fetchone()
            if sweep is None:
                raise HTTPException(404, "Unknown project sweep")
            rows = db.execute("""SELECT id,status,error,runtime,json_extract(result,'$.passed') AS passed,
                   coalesce(json_extract(result,'$.summary'),json_extract(result,'$.metrics')) AS metrics,
                   json_extract(result,'$.numerical_diagnostics.passed') AS diagnostics_passed,
                   json_extract(result,'$.dynamics.reference_qualification') AS qualification
                   FROM project_runs WHERE project_id=? AND suite_id=? ORDER BY ordinal""", (project, suite_id)).fetchall()
        return _summarize(suite_id, json.loads(sweep["definition"]), rows)

    @router.post("", status_code=202)
    def submit(project: str, spec: Sweep, idempotency_key: str | None = Header(None)):
        with runs.store.connection() as db:
            runs.store._required(db, "projects", project)
            row = db.execute("SELECT snapshot FROM project_revisions WHERE project_id=? AND revision=?",
                             (project, spec.expected_revision)).fetchone()
        if row is None:
            raise HTTPException(409, "Unknown project revision")
        try:
            definition, tests = _plan(spec, json.loads(row["snapshot"]))
        except (ValueError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc
        receipt = runs.submit(project, spec.expected_revision, tests, idempotency_key, sweep=definition)
        return detail(project, receipt["suite_id"])

    return router
