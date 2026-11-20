"""Compare an immutable run's acceptance measurements with an attributed physical trial."""
import csv
import io
import json
import math
import sys
from decimal import Decimal, DecimalException, localcontext

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .project_bindings import UNIT_FACTORS
from .packaging_lift import LIFT_ADAPTERS
from .campaign_coverage import coverage_factor_labels, flatten_controls


COLUMNS = ("run_id", "evidence_hash", "prototype_id", "trial_id", "condition_record",
           "simulated_settings_json", "trial_settings_json",
           "metric", "unit", "measured_value", "absolute_uncertainty")
MAX_ROWS = 512


def _number(value):
    return type(value) in (int, float) and -sys.float_info.max <= value <= sys.float_info.max


def run_settings(run):
    result = run.get("result") or {}
    inputs = flatten_controls(result.get("inputs") or run.get("inputs") or {})
    if run["adapter"] in LIFT_ADAPTERS:
        inputs.update(result.get("summary") or {})
    return {key: inputs[key] for key in coverage_factor_labels(run["adapter"], inputs)
            if _number(inputs.get(key))}


def _settings(text):
    def unique(pairs):
        obj = dict(pairs)
        if len(obj) != len(pairs):
            raise ValueError("A trial setting was listed twice")
        return obj
    try:
        values = json.loads(text, object_pairs_hook=unique)
    except (ValueError, RecursionError) as error:
        raise ValueError("Use one JSON object of finite numeric settings in the native model units") from error
    if not isinstance(values, dict) or any(not _number(n) for n in values.values()):
        raise ValueError("Use one JSON object of finite numeric settings in the native model units")
    return values


def acceptance_metrics(run):
    """Only quantities with a recorded numeric upper limit and known physical units."""
    result = run["result"] or {}
    summary = result.get("summary") or result.get("metrics") or {}
    metrics = {}

    def add(key, value, maximum, unit, numerical_slack=0):
        if _number(value) and _number(maximum) and unit:
            metrics[key] = {"prediction": value, "maximum": maximum, "unit": unit,
                            "simulation_verdict": "pass" if value <= maximum + numerical_slack else "fail"}

    units = {"continuous_max_surface_stress_pa": "Pa", "continuous_max_abs_displacement_m": "m",
             "continuous_peak_temperature_k": "K"}
    for check in result.get("acceptance_checks", []):
        key = check["quantity"]
        add(key, check["measured"], check["maximum"], units.get(key))
    # V2 needs a physical pulse trace aligned to cycle start to compare these
    # phase measurements. The current CSV only attests scalar settings.
    if run["adapter"] == "packaging_lift":
        fixture = result.get("fixture", {})
        for key in ("max_hold_error_m", "arrival_error_m"):
            add(key, summary.get(key), summary.get("error_limit_m", fixture.get("error_limit_m")), "m")
        add("peak_speed_m_s", summary.get("peak_speed_m_s"), fixture.get("speed_limit_m_s"), "m/s")
    if run["adapter"] == "robot_motion":
        for joint in result.get("model", {}).get("joints", []):
            name, unit = joint.get("name"), joint.get("unit")
            if not name or not unit:
                continue
            add(f"final_absolute_joint_error.{name}", summary.get("final_absolute_joint_error", {}).get(name),
                result.get("criteria", {}).get("joint_target_tolerance"), unit)
            add(f"peak_joint_speed.{name}", summary.get("peak_joint_speed", {}).get(name),
                joint.get("velocity_limit"), unit + "/s", numerical_slack=1e-9)
    return metrics


def evaluate_trials(stream, run, metrics):
    reader = csv.DictReader(stream, strict=True)
    if not reader.fieldnames or sorted(reader.fieldnames) != sorted(COLUMNS):
        raise ValueError("Use the columns in the run-specific hardware trial template")
    seen, trial_settings, rows = set(), {}, []
    expected = run_settings(run)
    for row in reader:
        line = reader.line_num
        if len(rows) >= MAX_ROWS:
            raise ValueError(f"Use at most {MAX_ROWS} measurements per file")
        if None in row or any(not value or not value.strip() or len(value) > (20000 if key.endswith("_json") else 1000)
                              for key, value in row.items()):
            raise ValueError(f"Row {line}: complete every column or remove the unused row")
        row = {key: value.strip() for key, value in row.items()}
        if row["run_id"] != run["id"] or row["evidence_hash"] != run["evidence_hash"]:
            raise ValueError(f"Row {line}: run ID or evidence hash differs from this simulation")
        if _settings(row["simulated_settings_json"]) != expected:
            raise ValueError(f"Row {line}: template settings differ from the saved simulation")
        actual = _settings(row["trial_settings_json"])
        differences = sorted(key for key in actual.keys() | expected.keys() if actual.get(key) != expected.get(key))
        trial = (row["prototype_id"], row["trial_id"])
        if trial_settings.setdefault(trial, actual) != actual:
            raise ValueError(f"Row {line}: operating settings changed within the same physical trial ID")
        key = row["metric"]
        if key not in metrics:
            raise ValueError(f"Row {line}: choose a metric with a recorded acceptance limit")
        metric = metrics[key]
        factor = UNIT_FACTORS.get(metric["unit"], {metric["unit"]: 1}).get(row["unit"])
        if factor is None:
            raise ValueError(f"Row {line}: use a unit compatible with {metric['unit']}")
        try:
            measured = float(row["measured_value"]) * factor
            uncertainty = float(row["absolute_uncertainty"]) * factor
        except ValueError:
            raise ValueError(f"Row {line}: enter numeric measurement and absolute uncertainty") from None
        if uncertainty < 0 or not all(math.isfinite(value) for value in
                                      (measured, uncertainty, measured - uncertainty, measured + uncertainty,
                                       measured - metric["prediction"])):
            raise ValueError(f"Row {line}: values must be finite, with nonnegative uncertainty")
        if measured < 0:
            raise ValueError(f"Row {line}: this absolute measurement must be nonnegative")
        identity = (*trial, key)
        if identity in seen:
            raise ValueError(f"Row {line}: duplicate prototype, trial and metric")
        seen.add(identity)
        try:
            with localcontext() as context:
                context.prec = 2 * max(len(row["measured_value"]), len(row["absolute_uncertainty"]), 32)
                measured_decimal = Decimal(row["measured_value"]) * Decimal(str(factor))
                uncertainty_decimal = Decimal(row["absolute_uncertainty"]) * Decimal(str(factor))
                if (measured_decimal < 0 or uncertainty_decimal < 0 or
                    (measured_decimal and not measured) or (uncertainty_decimal and not uncertainty)):
                    raise ValueError(f"Row {line}: values must be nonnegative and representable in the model unit")
                maximum = Decimal(str(metric["maximum"]))
                physical = ("pass" if measured_decimal + uncertainty_decimal <= maximum else
                            "fail" if measured_decimal - uncertainty_decimal > maximum else "indeterminate")
        except DecimalException as error:
            raise ValueError(f"Row {line}: measurement precision or exponent is outside the supported range") from error
        predicted = metric["simulation_verdict"]
        rows.append({**{k: row[k] for k in ("prototype_id", "trial_id", "condition_record", "metric")},
                     **metric, "measured": measured, "uncertainty": uncertainty,
                     "source_value": row["measured_value"], "source_uncertainty": row["absolute_uncertainty"],
                     "source_unit": row["unit"],
                     "residual": measured - metric["prediction"], "physical_verdict": physical,
                     "simulation_verdict": predicted, "trial_settings": actual, "differing_settings": differences,
                     "agreement": "unmatched settings" if differences or not expected else
                                  "indeterminate" if physical == "indeterminate" else
                                  "agrees" if physical == predicted else "disagrees"})
    if not rows:
        raise ValueError("The file contains no hardware measurements")
    return rows


def hardware_trial_router(runs):
    router = APIRouter(prefix="/api/projects/{project}/analysis/{run}/hardware-trials", tags=["hardware trials"])

    def inputs(project, run):
        record = runs.get(project, run)
        if record["status"] != "completed" or record["assessment_error"] or not record["evidence_hash"]:
            raise HTTPException(409, "This check needs a completed run with valid numerical evidence")
        return record, acceptance_metrics(record)

    @router.get("")
    def available(project: str, run: str):
        _, metrics = inputs(project, run)
        assets = runs.projects.get(project)["assets"]
        return {"metrics": metrics, "assets": [
            {"id": a["id"], "filename": a["filename"]} for a in assets
            if a["kind"] == "measurements" and a["filename"].lower().endswith(".csv")]}

    @router.get("/template.csv")
    def template(project: str, run: str):
        record, metrics = inputs(project, run)
        if not metrics:
            raise HTTPException(409, "This run has no supported numeric acceptance limit")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=COLUMNS)
        writer.writeheader()
        for key, metric in metrics.items():
            writer.writerow({"run_id": record["id"], "evidence_hash": record["evidence_hash"],
                             "simulated_settings_json": json.dumps(run_settings(record), sort_keys=True, allow_nan=False),
                             "metric": key, "unit": metric["unit"]})
        return Response(output.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="hardware-trial-{record["id"]}.csv"'})

    @router.get("/{asset}")
    def compare(project: str, run: str, asset: str):
        record, metrics = inputs(project, run)
        info, path = runs.projects.asset(project, asset)
        if info["kind"] != "measurements" or not info["filename"].lower().endswith(".csv"):
            raise HTTPException(422, "Choose a physical measurements CSV from this project")
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = evaluate_trials(stream, record, metrics)
        except (csv.Error, UnicodeError, ValueError) as error:
            raise HTTPException(422, str(error)) from error
        return {"run_id": record["id"], "project_revision": record["project_revision"],
                "evidence_hash": record["evidence_hash"], "asset_id": asset, "asset_sha256": info["sha256"],
                "simulated_settings": run_settings(record), "rows": rows}

    return router
