"""Bounded CAD exchange and held-out physical log calibration for projects."""
from __future__ import annotations

import csv
import io
import struct
from typing import Literal

import numpy as np
from pydantic import Field, FiniteFloat, model_validator
from scipy.optimize import minimize_scalar

from .projects import IntakeModel


class CadInventory(IntakeModel):
    cad_asset_id: str = Field(pattern=r"^asset_[0-9a-f]{32}$")
    units: Literal["mm", "cm", "m"]
    component: str = Field(min_length=1, max_length=100)
    bom_asset_id: str | None = Field(default=None, pattern=r"^asset_[0-9a-f]{32}$")


def csv_rows(data, headers, limit):
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("CSV exceeds the 2 MiB analysis limit")
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")), strict=True)
        if reader.fieldnames != headers:
            raise ValueError("Expected CSV columns in order: " + ",".join(headers))
        rows = []
        for row in reader:
            if len(rows) >= limit or set(row) != set(headers) or any(not v or not v.strip() for v in row.values()):
                raise ValueError("CSV contains an incomplete or excess row")
            rows.append(row)
        if not rows:
            raise ValueError("CSV has no data rows")
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Expected a UTF-8 CSV file") from exc


def inspect_cad(spec: CadInventory, mesh: bytes, bom: bytes | None):
    # An STL has no unit metadata, including when the header starts with 'solid'.
    scale = {"mm": 0.001, "cm": 0.01, "m": 1.0}[spec.units]
    count = int.from_bytes(mesh[80:84], "little")
    if len(mesh) >= 84 and len(mesh) == 84 + count * 50:
        if not 1 <= count <= 100_000:
            raise ValueError("STL must have 1 to 100000 triangles")
        vertices = np.array([face[3:12] for face in struct.iter_unpack("<12fH", mesh[84:])])
    else:
        lines = iter(line.strip().split() for line in mesh.decode("ascii").splitlines() if line.strip())
        if next(lines, [])[:1] != ["solid"]:
            raise ValueError("Expected a binary or ASCII STL solid")
        vertices = []
        for fields in lines:
            if fields[:1] == ["endsolid"]:
                if next(lines, None) is not None:
                    raise ValueError("Only single-solid ASCII STL files are supported")
                break
            if fields[:2] != ["facet", "normal"] or len(fields) != 5 or next(lines, []) != ["outer", "loop"]:
                raise ValueError("Invalid STL facet")
            triangle = []
            for _ in range(3):
                point = next(lines, [])
                if len(point) != 4 or point[0] != "vertex":
                    raise ValueError("Invalid STL vertex")
                triangle.extend(map(float, point[1:]))
            if next(lines, []) != ["endloop"] or next(lines, []) != ["endfacet"]:
                raise ValueError("Incomplete STL facet")
            vertices.append(triangle)
            if len(vertices) > 100_000:
                raise ValueError("STL exceeds 100000 triangles")
        else:
            raise ValueError("Missing STL endsolid")
    if not len(vertices):
        raise ValueError("STL contains no triangles")
    world = np.asarray(vertices, dtype=np.float64).reshape(-1, 3, 3) * scale
    if not np.isfinite(world).all() or np.max(np.abs(world)) > 1e5:
        raise ValueError("STL coordinates exceed the supported finite scale")
    areas = np.linalg.norm(np.cross(world[:, 1]-world[:, 0], world[:, 2]-world[:, 0]), axis=1) / 2
    if np.any(areas <= 0):
        raise ValueError("STL contains zero-area triangles")
    mapping = None
    if bom is not None:
        rows = csv_rows(bom, ["component", "material", "source"], 1000)
        matches = [r for r in rows if r["component"] == spec.component]
        if len(matches) != 1:
            raise ValueError("BOM must contain exactly one row matching the named component")
        mapping = matches[0]
    minimum, maximum = world.min(axis=(0, 1)), world.max(axis=(0, 1))
    indices = np.linspace(0, len(world)-1, min(300, len(world)), dtype=int)
    return {"summary": {"triangles": len(world), "surface_area_m2": float(areas.sum())},
            "bounds_m": {"minimum": minimum.tolist(), "maximum": maximum.tolist()},
            "preview_triangles_m": world[indices].tolist(), "preview_total_triangles": len(indices),
            "component": spec.component, "material_assignment": mapping,
            "assumptions": ["One tessellated component; scale is declared by the operator.",
                            "Surface inventory only. No enclosed volume, mass, joint, or material strength inferred."]}


class JointResponse(IntakeModel):
    joint_name: str = Field(min_length=1, max_length=100)
    hardware_revision: str = Field(min_length=1, max_length=150)
    training_asset_id: str = Field(pattern=r"^asset_[0-9a-f]{32}$")
    validation_asset_id: str = Field(pattern=r"^asset_[0-9a-f]{32}$")
    min_time_constant_s: FiniteFloat = Field(default=0.005, ge=0.001, le=1000)
    max_time_constant_s: FiniteFloat = Field(default=5, ge=0.001, le=1000)
    max_validation_rmse_rad: FiniteFloat = Field(gt=0, le=3.15)

    @model_validator(mode="after")
    def distinct(self):
        if self.training_asset_id == self.validation_asset_id or self.min_time_constant_s >= self.max_time_constant_s:
            raise ValueError("Supply separate fit and validation logs and ordered bounds")
        return self


def _joint_log(data):
    fields = ["time_s", "command_rad", "position_rad"]
    rows = csv_rows(data, fields, 5000)
    values = np.array([[float(row[k]) for k in fields] for row in rows])
    if len(rows) < 4 or not np.isfinite(values).all() or np.any(np.diff(values[:, 0]) <= 0):
        raise ValueError("Logs need at least four finite, strictly time-ordered samples")
    if np.max(np.abs(values[:, 1:])) > 100 or np.ptp(values[:, 0]) > 86400:
        raise ValueError("Log exceeds supported angle or duration bounds")
    if np.max(np.abs(values[:-1, 1] - values[0, 2])) < 1e-6:
        raise ValueError("Commanded motion is insufficient to identify a time constant")
    return values


def fit_joint_response(spec, training, validation):
    fit, holdout = _joint_log(training), _joint_log(validation)
    if fit.shape == holdout.shape and np.array_equal(fit[:, 1:], holdout[:, 1:]):
        # An exported trajectory may use elapsed time in one file and absolute time in another.
        # Only clock intervals enter the recurrence. Allow rounding at the original clock magnitude.
        time_roundoff = 4 * max(np.spacing(np.max(np.abs(t[:, 0]))) for t in (fit, holdout))
        if np.allclose(np.diff(fit[:, 0]), np.diff(holdout[:, 0]), rtol=0, atol=time_roundoff):
            raise ValueError("The held-out log duplicates the training samples")
    def simulate(log, tau):
        decay = np.exp(-np.diff(log[:, 0]) / tau)
        prediction = np.empty(len(log))
        prediction[0] = log[0, 2]
        for i, factor in enumerate(decay):
            prediction[i+1] = factor * prediction[i] + (1 - factor) * log[i, 1]
        return prediction
    def loss(tau):
        return np.mean((simulate(fit, tau)[1:] - fit[1:, 2]) ** 2)
    lower, upper = spec.min_time_constant_s, spec.max_time_constant_s
    opt = minimize_scalar(loss, bounds=(lower, upper), method="bounded",
                          options={"xatol": max(1e-11, lower*1e-7)})
    tau = float(opt.x)
    if not opt.success or min(tau-lower, upper-tau) < 1e-5 * (upper-lower):
        raise ValueError("Unresolved fit at the parameter boundary; review measurements and units")
    predictions = {}
    metrics = {"time_constant_s": tau}
    for name, log in (("fit", fit), ("validation", holdout)):
        predicted = simulate(log, tau)
        residual = predicted - log[:, 2]
        metrics[name + "_rmse_rad"] = float(np.sqrt(np.mean(residual[1:]**2)))
        predictions[name] = {"time_s": log[:, 0].tolist(), "command_rad": log[:, 1].tolist(),
                             "position_rad": log[:, 2].tolist(), "predicted_rad": predicted.tolist(),
                             "residual_rad": residual.tolist()}
    return {"summary": metrics, "passed": metrics["validation_rmse_rad"] <= spec.max_validation_rmse_rad,
            "traces": predictions,
            "parameter": {"name": spec.joint_name + " time constant", "unit": "s", "value": tau},
            "assumptions": ["Single rotational joint, aligned clocks and radians. Commands are held between samples.",
                            "Held-out error excludes the measured initial condition. Valid only for this hardware revision and observed operating conditions."]}
