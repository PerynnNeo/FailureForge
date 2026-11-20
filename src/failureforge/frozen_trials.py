"""Freeze a scalar prediction before recording a separately attributed physical observation."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import AwareDatetime, Field, FiniteFloat, StrictBool, model_validator

from .contracts import canonical_json, config_hash, utc_now
from .hardware_trials import acceptance_metrics, run_settings
from .persistence import new_id
from .project_bindings import FIELD_UNITS, UNIT_FACTORS
from .project_bundle import evidence
from .projects import IntakeModel

Name = Annotated[str, Field(min_length=1, max_length=160)]
Note = Annotated[str, Field(min_length=1, max_length=3000)]
Number = Annotated[FiniteFloat, Field(strict=True)]
Station = Literal["free_end", "from_origin", "whole_fixture", "unknown"]
# Each entry is a scale and an origin offset. Offsets apply only to the
# observation; an uncertainty in degrees Celsius has the same size in kelvin.
MEASUREMENT_CONVERSIONS = {
    "K": {"K": (1, 0), "°C": (1, 273.15)},
    "m/s": {"m/s": (1, 0), "cm/s": (0.01, 0), "mm/s": (0.001, 0)},
    "rad/s": {"rad/s": (1, 0), "mrad/s": (0.001, 0)},
}


def conversions(unit):
    if unit in MEASUREMENT_CONVERSIONS:
        return MEASUREMENT_CONVERSIONS[unit]
    return {key: (scale, 0) for key, scale in UNIT_FACTORS.get(unit, {unit: 1}).items()}


class PredictionRequest(IntakeModel):
    observable_id: Name
    prototype_id: Name
    setup: Note


class PhysicalReading(IntakeModel):
    prototype_id: Name
    trial_id: Name
    source: Note
    condition_record: Note
    source_kind: Literal["published", "new_trial"]
    measured_at: AwareDatetime | None = None
    independent: StrictBool
    fixture_matches: StrictBool
    actual_settings: dict[Name, Number] = Field(max_length=100)
    station_reference: Station
    station_m: Annotated[Number, Field(ge=0)] | None = None
    value: Number
    unit: Name
    uncertainty: Annotated[Number, Field(gt=0)] | None
    uncertainty_basis: Note
    asset_id: Name | None = None

    @model_validator(mode="after")
    def provenance(self):
        if self.source_kind == "new_trial" and self.measured_at is None:
            raise ValueError("Supply the acquisition time for a new physical trial.")
        if self.station_reference == "from_origin" and self.station_m is None:
            raise ValueError("Enter the physical station in metres from the model origin.")
        if self.station_reference != "from_origin" and self.station_m is not None:
            raise ValueError("A station in metres requires the from-origin station convention.")
        return self


def observables(run):
    result = run["result"]
    inputs = result.get("inputs") or {}
    traces = result.get("traces") or {}
    entries = []

    def add(key, label, value, unit, reference="whole_fixture", station=None, nonnegative=True):
        if type(value) in (int, float) and math.isfinite(value):
            entries.append({"id": key, "label": label, "prediction": value, "unit": unit,
                            "units": list(conversions(unit)),
                            "station_reference": reference, "station_m": station, "nonnegative": nonnegative})

    if run["adapter"] in ("structural_beam", "thermal_rod"):
        beam = run["adapter"] == "structural_beam"
        key, title, unit = ("displacement_m", "Signed transverse deflection", "m") if beam else (
            "temperature_k", "Steady rod temperature", "K")
        x = traces.get("node_position_m") or []
        values = traces.get(key) or []
        # Stiffness is a ratio for a pure, linear transverse probe at the free end.
        # A combined-load displacement includes responses to other forces.
        if beam and x and len(values) == len(x):
            force = inputs.get("tip_force_n")
            if (force and values[-1] and result.get("numerical_diagnostics", {}).get("passed") is True
                    and result.get("summary", {}).get("within_small_deflection_screen") is True
                    and not any(inputs.get(k) for k in ("distributed_load_n_per_m", "face_pressure_pa", "span_loads"))
                    and force / values[-1] > 0):
                add("tip_stiffness_n_per_m", "Free-end transverse stiffness", force / values[-1],
                    "N/m", "free_end", x[-1])
        if len(values) == len(x):
            for i, (station, value) in enumerate(zip(x, values)):
                add(f"{key}@{i}", f"{title} at {station:.8g} m", value, unit, "from_origin", station, not beam)
    for key, metric in acceptance_metrics(run).items():
        add(key, key.replace("_", " "), metric["prediction"], metric["unit"])
    return entries


def operating_settings(run, observable):
    # Stiffness in this model is load-independent. The location (free end),
    # boundary fixture, specimen and test direction define the physical comparison.
    if observable["id"] == "tip_stiffness_n_per_m":
        return {}
    settings = run_settings(run)
    result = run["result"]
    if run["adapter"] == "packaging_lift":
        fixture = result.get("fixture", {})
        for key in ("target_m", "arrival_deadline_s", "end_time_s"):
            if key in fixture:
                settings[key] = fixture[key]
    if run["adapter"] == "robot_motion":
        trajectory = result.get("trajectory", {})
        times = trajectory.get("time_s", [])
        if times:
            settings["duration_s"] = times[-1] - times[0]
        for joint in result.get("model", {}).get("joints", []):
            name = joint["name"]
            positions = trajectory.get("joint_positions", {}).get(name, [])
            if positions and not joint.get("mimic"):
                settings[f"initial.{name}"] = positions[0]
                settings.setdefault(f"targets.{name}", positions[0])
    return settings


def setting_units(run, settings):
    units = dict(FIELD_UNITS.get(run["adapter"], {}))
    units.update(target_m="m", arrival_deadline_s="s", end_time_s="s")
    for key in settings:
        if key.startswith("span_loads."):
            units[key] = "N" if key.endswith(".force_n") else "fraction of span"
    for joint in run["result"].get("model", {}).get("joints", []):
        for field in ("initial", "targets"):
            units[field + "." + joint["name"]] = joint["unit"]
    return {key: units.get(key, "") for key in settings}


def compare_reading(prediction, reading):
    observable = prediction["observable"]
    # A freeze owns its advertised source units even if a future release adds more.
    conversion = conversions(observable["unit"]).get(reading.unit)
    if conversion is None or reading.unit not in observable["units"]:
        raise HTTPException(422, f"Choose a unit compatible with {observable['unit']}.")
    if reading.measured_at and reading.measured_at > datetime.now(timezone.utc):
        raise HTTPException(422, "Acquisition time must be in the past.")
    if reading.source_kind == "new_trial" and reading.measured_at < datetime.fromisoformat(prediction["frozen_at"]):
        raise HTTPException(422, "This observation predates the freeze. Record it as existing evidence.")
    predicted = Decimal(str(observable["prediction"]))
    scale, offset = conversion
    factor = Decimal(str(scale))
    value = Decimal(str(reading.value)) * factor + Decimal(str(offset))
    if observable["unit"] == "K" and value <= 0:
        raise HTTPException(422, "Absolute temperature must be above zero kelvin.")
    if observable["nonnegative"] and value < 0:
        raise HTTPException(422, "This quantity requires a nonnegative measurement.")
    uncertainty = None if reading.uncertainty is None else Decimal(str(reading.uncertainty)) * factor
    interval = None if uncertainty is None else [value - uncertainty, value + uncertainty]
    residual = value - predicted
    if any(not math.isfinite(float(v)) or (v and not float(v)) for v in [value, residual, *(interval or []), uncertainty or 0]):
        raise HTTPException(422, "Use values representable in the prediction unit.")
    expected = prediction["settings"]
    actual = reading.actual_settings
    different = [k for k in sorted(actual.keys() | expected.keys()) if k not in actual or k not in expected
                 or not math.isclose(actual[k], expected[k], rel_tol=1e-10, abs_tol=0)]
    issues = []
    if prediction["prototype_id"] != reading.prototype_id:
        issues.append("Specimen ID differs from the frozen prediction.")
    if not reading.fixture_matches:
        issues.append("Fixture, measurement definition or operating setup is unconfirmed.")
    if (reading.station_reference != observable["station_reference"] or
            (reading.station_reference == "from_origin" and
             not math.isclose(reading.station_m, observable["station_m"], rel_tol=1e-10, abs_tol=0))):
        issues.append("Physical measurement station differs or is unknown.")
    if different:
        issues.append("Missing or differing operating settings: " + ", ".join(different))
    if not expected and observable["id"] != "tip_stiffness_n_per_m":
        issues.append("No physical operating settings were recorded in this run.")
    if not reading.independent:
        issues.append("Independence from model fitting is unconfirmed.")
    if interval is None:
        issues.append("Measurement uncertainty is unavailable.")
    conclusion = "indeterminate" if issues else "agrees" if interval[0] <= predicted <= interval[1] else "disagrees"
    return {"conclusion": conclusion, "reasons": issues, "measured": float(value), "residual": float(residual),
            "unit": observable["unit"], "interval": [float(v) for v in interval] if interval else None}


def frozen_trial_router(runs):
    router = APIRouter(prefix="/predictions")
    with runs.store.connection(True) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS frozen_predictions (
                   id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES project_runs(id), record TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS physical_readings (
                   id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL REFERENCES frozen_predictions(id),
                   trial_id TEXT NOT NULL, record TEXT NOT NULL, UNIQUE(prediction_id, trial_id))""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_frozen_predictions_run ON frozen_predictions(run_id)")

    def verified_run(db, project, run):
        record = runs.get_in_transaction(db, project, run)
        if record["status"] != "completed" or record["assessment_error"] or not record["result"]:
            raise HTTPException(409, "Choose a completed run with applicable numerical evidence.")
        evidence(record)
        return record

    def checked_record(row):
        data = json.loads(row["record"])
        if data["hash"] != config_hash({k: v for k, v in data.items() if k != "hash"}):
            raise HTTPException(409, "Stored trial evidence checksum differs.")
        return data

    def load_prediction(db, project, run, identifier):
        runs.get_in_transaction(db, project, run)
        row = db.execute("SELECT record FROM frozen_predictions WHERE run_id=? AND id=?", (run, identifier)).fetchone()
        if not row:
            raise HTTPException(404, "Frozen prediction missing for this run.")
        return checked_record(row)

    def key_check(key):
        if not 8 <= len(key) <= 200:
            raise HTTPException(422, "Supply an Idempotency-Key of 8 to 200 characters.")

    @router.get("")
    def list_predictions(project: str, run: str):
        with runs.store.connection() as db:
            record = verified_run(db, project, run)
            rows = db.execute("SELECT record FROM frozen_predictions WHERE run_id=? ORDER BY rowid DESC", (run,))
            return {"observables": observables(record), "predictions": [checked_record(row) for row in rows]}

    @router.post("", status_code=201)
    def freeze(project: str, run: str, body: PredictionRequest, idempotency_key: str = Header()):
        key_check(idempotency_key)
        payload, scope = body.model_dump(), "prediction:" + run
        with runs.store.connection(True) as db:
            record = verified_run(db, project, run)
            existing = runs.store._idempotent(db, scope, idempotency_key, payload)
            if existing:
                return existing
            observable = next((item for item in observables(record) if item["id"] == body.observable_id), None)
            if observable is None:
                raise HTTPException(422, "Choose a recorded observable available on this run.")
            settings = operating_settings(record, observable)
            prediction = {**payload, "id": new_id("prediction"), "frozen_at": utc_now(), "project_id": project,
                          "project_revision": record["project_revision"], "run_id": run, "adapter": record["adapter"],
                          "evidence_hash": record["evidence_hash"], "observable": observable,
                          "settings": settings, "setting_units": setting_units(record, settings),
                          "model_inputs": record["result"].get("inputs") or record["inputs"],
                          "fixture": record["result"].get("fixture"),
                          "assumptions": record["result"].get("assumptions", [])}
            prediction["hash"] = config_hash(prediction)
            db.execute("INSERT INTO frozen_predictions VALUES(?,?,?)", (prediction["id"], run, canonical_json(prediction)))
            runs.store._remember(db, scope, idempotency_key, payload, prediction)
            return prediction

    @router.get("/{identifier}")
    def get_prediction(project: str, run: str, identifier: str):
        with runs.store.connection() as db:
            prediction = load_prediction(db, project, run, identifier)
            rows = db.execute("SELECT record FROM physical_readings WHERE prediction_id=? ORDER BY rowid", (identifier,))
            return {"prediction": prediction, "measurements": [checked_record(row) for row in rows]}

    @router.post("/{identifier}/measurements", status_code=201)
    def enter_reading(project: str, run: str, identifier: str, body: PhysicalReading, idempotency_key: str = Header()):
        key_check(idempotency_key)
        payload, scope = body.model_dump(mode="json"), "physical-reading:" + identifier
        with runs.store.connection(True) as db:
            frozen = load_prediction(db, project, run, identifier)
            existing = runs.store._idempotent(db, scope, idempotency_key, payload)
            if existing:
                return existing
            if db.execute("SELECT 1 FROM physical_readings WHERE prediction_id=? AND trial_id=?",
                          (identifier, body.trial_id)).fetchone():
                raise HTTPException(409, "A measurement with this trial ID is already recorded for this prediction.")
            asset = None
            if body.asset_id:
                row = db.execute("SELECT id,sha256,filename FROM project_assets WHERE project_id=? AND id=? AND kind='measurements'",
                                 (project, body.asset_id)).fetchone()
                if not row:
                    raise HTTPException(422, "Choose a physical measurement asset attached to this project.")
                asset = dict(row)
            reading = {**payload, **compare_reading(frozen, body), "source_unit": body.unit,
                       "id": new_id("reading"), "recorded_at": utc_now(), "prediction_hash": frozen["hash"], "asset": asset}
            reading["hash"] = config_hash(reading)
            db.execute("INSERT INTO physical_readings VALUES(?,?,?,?)",
                       (reading["id"], identifier, body.trial_id, canonical_json(reading)))
            runs.store._remember(db, scope, idempotency_key, payload, reading)
            return reading

    return router
