"""Read the outcomes and controls actually recorded for a scenario comparison."""
from .artifacts import ArtifactError
from .contracts import config_hash
from .project_bundle import evidence


def applied_change(report):
    if not report or not report.get("variant"):
        return None
    variant = report["variant"]
    inputs = variant["inputs"]
    label = variant["label"]
    if variant["adapter"] == "structural_beam":
        loads = []
        for patch in inputs.get("span_loads", []):
            start, end = 100 * patch["start_fraction"], 100 * patch["end_fraction"]
            location = f"at {start:g}%" if start == end else f"over {start:g}–{end:g}%"
            loads.append(f"{patch['force_n']:g} N {location} of span")
        if tip := inputs.get("tip_force_n"):
            loads.append(f"{tip:g} N at free end")
        if line := inputs.get("distributed_load_n_per_m"):
            loads.append(f"{line:g} N/m across full span")
        if pressure := inputs.get("face_pressure_pa"):
            loads.append(f"{pressure:g} Pa across full face")
        return ", ".join(loads) or "External applied load removed (0 N)"
    if variant["adapter"] == "packaging_lift_timed_v2":
        return f"Press starts at {inputs['head_onset_ms']} ms and lasts {inputs['head_duration_ms']} ms"
    return label


def _measurement(reference, variant):
    summary = variant.get("summary", {})
    before = reference.get("summary", {})
    checks = variant.get("acceptance_checks", [])
    # Prefer a failed requirement if more than one was tested.
    for check in sorted(checks, key=lambda row: row.get("passed") is not False):
        if not isinstance(check.get("measured"), (float, int)):
            continue
        key = check["quantity"]
        name, scale, unit = {
            "continuous_max_abs_displacement_m": ("Maximum deflection", 1000, "mm"),
            "continuous_max_surface_stress_pa": ("Maximum bending stress", 1e-6, "MPa"),
        }.get(key, (key.replace("_", " "), 1, ""))
        old = before.get(key)
        return {"name": name, "unit": unit, "value": check["measured"] * scale,
                "reference_value": None if old is None else old * scale, "limit": check["maximum"] * scale}
    if "arrival_error_m" in summary:
        arrival_failed = variant.get("criteria", {}).get("arrived_within_tolerance") is False
        key = "arrival_error_m" if arrival_failed else "max_hold_error_m"
        return {"name": "Arrival error" if arrival_failed else "Maximum hold error",
                "value": summary[key] * 1000, "reference_value": before[key] * 1000, "unit": "mm",
                "limit": summary["error_limit_m"] * 1000}
    return None


def verified_run(runs, db, project_id, run_id):
    try:
        row = runs.get_in_transaction(db, project_id, run_id)
    except KeyError:
        return None
    if row["status"] == "completed":
        try:
            evidence(row)
        except ArtifactError as exc:
            row["assessment_error"] = str(exc)
    return row


def recorded_outcome(reference, variant, expected_runtime=None):
    """Return an assessment only for completed, valid measured evidence from both runs."""
    results = []
    for role, row in (("Reference", reference), ("What-if", variant)):
        if row is None:
            return "inconclusive", f"{role} run is missing.", None
        result = row["result"]
        if row["status"] in ("queued", "running"):
            results.append(None)
            continue
        problem = row["error"] or row["assessment_error"]
        if row["status"] != "completed" or not result or not row["evidence_hash"] or problem:
            return "inconclusive", f"{role}: {problem or row['status'] + ' without assessable evidence'}", None
        results.append(result)
        if expected_runtime and config_hash(row["runtime"]) != expected_runtime:
            return "inconclusive", f"{role} used a different solver version than the saved experiment.", None
    if None in results:
        active = "running" if any(row["status"] == "running" for row in (reference, variant)) else "queued"
        return active, "Waiting for the reference and test measurements.", None
    left, right = results
    if reference["runtime"] != variant["runtime"] or reference["adapter"] != variant["adapter"]:
        return "inconclusive", "The recorded solvers differ between the reference and the what-if.", None
    metric = _measurement(left, right)
    verdict = right.get("passed")
    if verdict is None:
        return "measurement_only", "Measurements were recorded without an overall acceptance verdict.", metric
    return ("passed" if verdict else "failed"), "Recorded solver verdict for this what-if.", metric
