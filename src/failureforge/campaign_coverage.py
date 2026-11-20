"""Summarize discrete operating conditions from immutable campaign inputs and assessed outcomes."""
from collections import defaultdict
from decimal import Decimal
from itertools import combinations, islice, product
import math
import sys

from .environment_matrices import LiftCondition
from .project_bindings import FIELD_UNITS, UNIT_FACTORS
from .project_sweeps import FIELDS


OBSERVED = {"passed", "failed", "measurement_only"}


def flatten_controls(inputs):
    """Keep unvaried inputs (including tolerances) when testing for an isolated change."""
    values = dict(inputs)
    if isinstance(values.get("targets"), dict):
        targets = values.pop("targets")
        values.update({f"targets.{name}": target for name, target in targets.items()})
    loads = values.get("span_loads")
    if isinstance(loads, list) and all(isinstance(item, dict) for item in loads):
        values.pop("span_loads")
        for i, load in enumerate(loads, 1):
            values.update({f"span_loads.{i}.{key}": value for key, value in load.items()})
    return values


def coverage_factor_labels(adapter, flattened_inputs):
    fields = dict(FIELDS.get(adapter, {}))
    if adapter == "structural_beam":
        for key in sorted(flattened_inputs):
            parts = key.split(".", 2)
            if (len(parts) == 3 and parts[0] == "span_loads" and parts[1].isdecimal()
                    and parts[2] in ("start_fraction", "end_fraction", "force_n")):
                fields[key] = f"Span load {parts[1]} · {parts[2].replace('_', ' ')}"
    if adapter == "packaging_lift":
        return {key: key.replace("_", " ").rsplit(" ", 1)[0].capitalize() for key in LiftCondition.model_fields}
    if adapter == "packaging_lift_timed_v2":
        return {"payload_kg": "Payload", "head_force_n": "Head force", "head_onset_ms": "Head engagement time",
                "head_duration_ms": "Head pulse duration"}
    if "targets.*" in fields:
        fields.pop("targets.*")
        fields.update({key: f"Joint target · {key.removeprefix('targets.')}"
                       for key in sorted(flattened_inputs) if key.startswith("targets.")})
    return fields


def factor_catalog(adapters):
    catalog = {}
    for adapter in adapters:
        name = adapter["id"]
        fields = coverage_factor_labels(name, ())
        if "targets.*" in FIELDS.get(name, {}):
            fields["targets.*"] = FIELDS[name]["targets.*"]
        for field, label in fields.items():
            catalog[field] = {"field": field, "label": label,
                              "unit": FIELD_UNITS.get(name, {}).get(field, "joint units")}
    return {"factors": list(catalog.values())}


def _declared_coverage(spec, factors):
    info = factors.get(spec.get("field"))
    required = spec.get("required_values", [])
    if info is None:
        return {**spec, "status": "unmapped", "untested_values": required}
    unit = spec.get("unit") or info["unit"]
    scale = UNIT_FACTORS.get(info["unit"], {info["unit"]: 1}).get(unit)
    if info["unit"] == "mixed joint units" or scale is None:
        return {**spec, "status": "unit_mismatch", "untested_values": None}
    observed = set(info["observed_values"])
    # Parameter bindings use floating-point multiplication. Accept either that
    # result or the correctly rounded decimal conversion without rounding nearby levels.
    def tested(value):
        return (value * scale in observed or
                float(Decimal(str(value)) * Decimal(str(scale))) in observed)

    return {**spec, "status": info["status"],
            "untested_values": [value for value in required if not tested(value)]}


def _coordinates(controls, labels):
    return {field: value for field, value in controls.items()
            if field in labels and type(value) in (int, float) and -sys.float_info.max <= value <= sys.float_info.max}


def _grid(records, axes):
    # Suites can mix boundary modes or different joint sets. A rectangular coverage
    # estimate only makes sense when the same numeric coordinates exist on every row.
    planned, observed = set(), set()
    levels = defaultdict(set)
    rectangular = bool(axes)
    for record in records:
        point = tuple((axis, record["point"][axis]) for axis in axes if axis in record["point"])
        if len(point) != len(axes):
            rectangular = False
        if not point:
            continue
        planned.add(point)
        if record["category"] in OBSERVED:
            observed.add(point)
        for axis, value in point:
            levels[axis].add(value)
    # Count products without enumerating them. Bound the serialized integer to
    # the largest value that JSON consumers using doubles can represent exactly.
    possible = math.prod(len(values) for values in levels.values()) if rectangular else None
    if possible is not None and possible > 2**53 - 1:
        possible = None
    counts = {"planned_cells": len(planned), "observed_cells": len(observed), "possible_cells": possible,
              "unobserved_cells": None if possible is None else possible - len(observed)}
    missing = []
    if possible is not None and possible > len(observed):
        # At most len(observed) + 16 product entries can be visited before the
        # preview is full, even when the hypothetical grid has billions of cells.
        candidates = product(*(sorted(levels[axis]) for axis in axes))
        unseen = (point for values in candidates if (point := tuple(zip(axes, values))) not in observed)
        missing = [dict(point) for point in islice(unseen, 16)]
    return counts, missing


def _group(adapter, records, declared, axes):
    joint_units = defaultdict(set)
    for record in records:
        for joint in record.get("joints", []):
            if joint.get("type") in ("revolute", "prismatic") and joint.get("mimic") is None:
                joint_units[f"targets.{joint['name']}"].add(joint["unit"])
    ambiguous = {key for key, units in joint_units.items() if len(units) > 1}
    labels = coverage_factor_labels(adapter, joint_units.keys() | {k for r in records for k in r["controls"]})
    counts = dict.fromkeys(("planned", "passed", "failed", "measurement_only", "pending", "blocked"), 0)
    for record in records:
        record["point"] = _coordinates({**record["controls"], **record.get("planned_coordinates", {})}, labels)
        for field in ambiguous:
            record["point"].pop(field, None)
        counts["planned"] += 1
        counts[record["category"]] += 1
    observed = [record for record in records if record["category"] in OBSERVED]
    factors = {}
    for field, label in labels.items():
        planned = sorted({r["point"][field] for r in records if field in r["point"]})
        values = sorted({r["point"][field] for r in observed if field in r["point"]})
        units = joint_units.get(field, set())
        unit = FIELD_UNITS.get(adapter, {}).get(field, "joint units")
        if adapter == "structural_beam" and field.startswith("span_loads."):
            unit = "N" if field.endswith(".force_n") else "1"
        if units:
            unit = next(iter(units)) if len(units) == 1 else "mixed joint units"
        factors[field] = {"field": field, "label": label, "unit": unit,
                          "planned_values": planned, "observed_values": values,
                          "status": "varied" if len(values) >= 2 else "fixed" if values else "unobserved",
                          "isolated_pairs": 0, "verdict_changes": 0}

    matched = None
    # A repeated setting that both passed and failed cannot anchor an attribution.
    # Compare numeric input values directly so 0 and 0.0 count as the same setting.
    def same_context(left, right):
        return all(left.get(key) == right.get(key) for key in ("revision", "runtime", "bindings"))

    conflicting = set()
    for left, right in combinations(observed, 2):
        if ({left["category"], right["category"]} == {"passed", "failed"}
                and same_context(left, right) and left["controls"] == right["controls"]):
            conflicting.update((left["id"], right["id"]))
    for left, right in combinations(observed, 2):
        if not same_context(left, right):
            continue
        a, b = left["controls"], right["controls"]
        changed = [key for key in a.keys() | b.keys() if key not in a or key not in b or a[key] != b[key]]
        if len(changed) != 1 or changed[0] not in left["point"] or changed[0] not in right["point"]:
            continue
        field = changed[0]
        factors[field]["isolated_pairs"] += 1
        if ({left["category"], right["category"]} != {"passed", "failed"}
                or left["id"] in conflicting or right["id"] in conflicting):
            continue
        factors[field]["verdict_changes"] += 1
        if matched is None:
            passed, failed = (left, right) if left["category"] == "passed" else (right, left)
            matched = {"field": field, "pass_run_id": passed["id"], "fail_run_id": failed["id"],
                       "pass_value": passed["point"][field], "fail_value": failed["point"][field]}

    if axes is None:
        axes = sorted(ambiguous | {field for r in records for field in r["point"]})
    grid, missing = _grid(records, axes)
    return {"adapter": adapter, "counts": counts, "factors": list(factors.values()), "conflicting_repeat_runs": sorted(conflicting),
            "declared_factors": [_declared_coverage(factor, factors) for factor in declared],
            "grid": grid, "missing_combinations": missing, "matched_change": matched}


def campaign_coverage(meta, records, declared, axes=None):
    grouped = defaultdict(list)
    for record in records:
        grouped[record["adapter"]].append(record)
    return {"project_id": meta["project_id"], "suite_id": meta["suite_id"], "kind": meta["kind"],
            "groups": [_group(adapter, members, declared, axes) for adapter, members in sorted(grouped.items())]}
