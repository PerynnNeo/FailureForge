"""Evaluate two external packaging loads on a single frozen project revision."""
from __future__ import annotations

import json
from itertools import product
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import Field, FiniteFloat, model_validator

from .project_runs import MAX_SUITE_TESTS, ProjectTest
from .project_solver import MODELS
from .projects import IntakeModel


Load = Annotated[FiniteFloat, Field(strict=True, ge=0)]
Axis = Annotated[list[Load], Field(min_length=2, max_length=MAX_SUITE_TESTS // 2)]


class LiftCondition(IntakeModel):
    payload_kg: Load
    head_force_n: Load


class EnvironmentMatrix(IntakeModel):
    expected_revision: int = Field(strict=True, ge=1)
    label: str = Field(min_length=1, max_length=100)
    adapter: Literal["packaging_lift"]
    payload_kg: Axis
    head_force_n: Axis
    reference: LiftCondition

    @model_validator(mode="after")
    def validate_grid(self):
        if len(self.payload_kg) * len(self.head_force_n) > MAX_SUITE_TESTS:
            raise ValueError(f"An environment matrix supports up to {MAX_SUITE_TESTS} cells")
        for field in LiftCondition.model_fields:
            values = getattr(self, field)
            if any(a >= b for a, b in zip(values, values[1:])):
                raise ValueError(f"{field} values must increase strictly")
            if getattr(self.reference, field) not in values:
                raise ValueError(f"The declared reference {field} must be on its axis")
        return self


def _coordinates(definition):
    for mass, force in product(definition["payload_kg"], definition["head_force_n"]):
        yield {"payload_kg": mass, "head_force_n": force}


def _assess(row, coordinates, reference_runtime):
    """Retain absolute task outcomes and separate missing, invalid and unfinished evidence."""
    if row is None:
        return "blocked", "Missing run for this planned condition"
    if json.loads(row["inputs"]) != coordinates:
        return "blocked", "Saved run inputs differ from the planned condition"
    if row["status"] in ("queued", "running"):
        return "pending", None
    if row["status"] != "completed" or row["error"]:
        return "blocked", row["error"] or f"Run is {row['status']}"
    if not row["runtime"] or not row["evidence_hash"] or row["diagnostics_passed"] != 1:
        return "blocked", "Missing execution evidence or unsuccessful numerical checks"
    if reference_runtime is not None and reference_runtime != row["runtime"]:
        return "blocked", "Solver runtime differs from the completed reference"
    if row["passed"] not in (0, 1):
        return "blocked", "The solver did not return a task outcome"
    return ("passed" if row["passed"] else "failed"), None


def _report(project, meta, rows):
    coordinates = list(_coordinates(meta))
    by_ordinal = {row["ordinal"]: row for row in rows}
    reference_row = by_ordinal.get(coordinates.index(meta["reference"]))
    reference_runtime = reference_row["runtime"] if reference_row and reference_row["status"] == "completed" else None
    counts = dict.fromkeys(("passed", "failed", "pending", "blocked"), 0)
    cells = []
    reference_passed = None
    for ordinal, condition in enumerate(coordinates):
        row = by_ordinal.get(ordinal)
        category, error = _assess(row, condition, reference_runtime)
        counts[category] += 1
        passed = category == "passed" if category in ("passed", "failed") else None
        is_reference = condition == meta["reference"]
        if is_reference:
            reference_passed = passed
        run_id = row["id"] if row else None
        evidence = row["evidence_hash"] if row else None
        cells.append({
            **condition, "reference": is_reference, "run_id": run_id,
            "status": row["status"] if row else "missing", "passed": passed, "error": error,
            "metrics": json.loads(row["metrics"]) if row and row["metrics"] else {},
            "evidence_hash": evidence,
            "bundle_url": f"/api/projects/{project}/analysis/{run_id}/bundle" if evidence else None,
        })
    status = "running" if counts["pending"] else "partial" if counts["blocked"] else "completed"
    return {**meta, "cells": cells, "status": status, "reference_passed": reference_passed,
            "counts": {"total": len(cells), **counts}}


def _metadata(row):
    return {**json.loads(row["definition"]), "created_at": row["created_at"], "suite_id": row["suite_id"]}


def environment_matrix_router(runs):
    router = APIRouter(prefix="/api/projects/{project}/environment-matrices", tags=["operating environments"])
    with runs.store.connection(True) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS project_environment_matrices(
            suite_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            definition TEXT NOT NULL, created_at TEXT NOT NULL)""")
        db.execute("""CREATE INDEX IF NOT EXISTS matrix_history
                      ON project_environment_matrices(project_id, created_at)""")

    @router.get("")
    def history(project: str):
        with runs.store.connection() as db:
            runs.store._required(db, "projects", project)
            rows = db.execute("""SELECT suite_id, definition, created_at FROM project_environment_matrices
                                WHERE project_id=? ORDER BY created_at DESC, suite_id LIMIT 200""", (project,))
            return {"matrices": [_metadata(row) for row in rows]}

    @router.get("/{suite_id}")
    def detail(project: str, suite_id: str):
        with runs.store.connection() as db:
            db.execute("BEGIN")
            row = db.execute("""SELECT suite_id, definition, created_at FROM project_environment_matrices
                               WHERE project_id=? AND suite_id=?""", (project, suite_id)).fetchone()
            if row is None:
                raise HTTPException(404, "Unknown environment matrix")
            rows = db.execute("""SELECT ordinal, id, status, runtime, inputs, evidence_hash, error,
                        json_extract(result, '$.summary') AS metrics, json_extract(result, '$.passed') AS passed,
                        json_extract(result, '$.numerical_diagnostics.passed') AS diagnostics_passed
                    FROM project_runs WHERE project_id=? AND suite_id=?""", (project, suite_id)).fetchall()
            return _report(project, _metadata(row), rows)

    @router.post("", status_code=202)
    def submit(project: str, spec: EnvironmentMatrix, idempotency_key: str | None = Header(None)):
        definition = {**spec.model_dump(exclude={"expected_revision"}), "project_revision": spec.expected_revision}
        tests = []
        for index, condition in enumerate(_coordinates(definition), start=1):
            try:
                MODELS[spec.adapter].model_validate(condition)
            except ValueError as exc:
                raise HTTPException(422, f"Invalid environment cell {index}: {exc}") from exc
            tests.append(ProjectTest(adapter=spec.adapter, inputs=condition, label=f"{spec.label} · cell {index}"))
        receipt = runs.submit(project, spec.expected_revision, tests, idempotency_key, environment_matrix=definition)
        return detail(project, receipt["suite_id"])

    return router
