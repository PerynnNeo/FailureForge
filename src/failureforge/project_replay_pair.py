"""Choose a recorded one-factor pass/fail comparison for a project's replay entry."""
import json
import math
from collections import defaultdict
from itertools import pairwise

from .campaign_coverage import coverage_factor_labels, flatten_controls
from .contracts import config_hash
from .project_validity import assessment_error


SEARCH_LIMIT = 200


def _condition(row, field, value, passed):
    return {"id": row["id"], "label": row["label"], "adapter": row["adapter"], "status": "completed",
            "passed": passed, "reference": False, "coordinates": {field: value}, "metrics": {}}


def replay_pair(db, project):
    # Project run results can contain long trajectories. Load only the evidence needed to
    # match the runs; their complete immutable results are retrieved when a user opens a pair.
    rows = db.execute("""
        SELECT id, label, adapter, suite_id, ordinal, project_revision, runtime,
               coalesce(json_extract(result,'$.inputs'), inputs) controls,
               json_extract(definition,'$.bindings') bindings,
               json_extract(result,'$.passed') passed,
               json_extract(result,'$.summary.within_small_deflection_screen') small_deflection,
               json_extract(result,'$.numerical_diagnostics.passed') diagnostics,
               json_extract(result,'$.dynamics.reference_qualification') qualification
        FROM project_runs
        WHERE project_id=? AND status='completed' AND error IS NULL AND evidence_hash IS NOT NULL
          AND json_type(runtime)='object' AND runtime!='{}'
          AND (coalesce(json_extract(result,'$.model.reference_id'),'')!='two_finger_hand_v1'
               OR json_extract(snapshot,'$.robot_template')='two_finger_hand_v1')
        ORDER BY created_at DESC, ordinal, id LIMIT ?
    """, (project, SEARCH_LIMIT)).fetchall()

    # Group by all fixed inputs, including model assets, acceptance thresholds and solver
    # settings. Restrict candidate changes to registered scalar factors for this adapter.
    groups = defaultdict(dict)
    ranges = {}
    for index, row in enumerate(rows):
        if row["passed"] is None or assessment_error({
            "summary": {"within_small_deflection_screen": row["small_deflection"] != 0},
            "numerical_diagnostics": {"passed": row["diagnostics"] != 0},
            "dynamics": {"reference_qualification": json.loads(row["qualification"] or "[]")},
        }):
            continue
        inputs = flatten_controls(json.loads(row["controls"]))
        cohort = (row["project_revision"], row["adapter"], row["runtime"], row["bindings"] or "{}")
        for field, label in coverage_factor_labels(row["adapter"], inputs).items():
            value = inputs.get(field)
            if type(value) not in (int, float) or not math.isfinite(value):
                continue
            axis = (*cohort, field)
            lo, hi = ranges.get(axis, (value, value))
            ranges[axis] = min(lo, value), max(hi, value)
            fixed = config_hash({key: val for key, val in inputs.items() if key != field})
            levels = groups[axis, label, fixed]
            # Keep the latest evidence for duplicate observations of the same verdict.
            levels.setdefault(value, {}).setdefault(bool(row["passed"]), (index, row))

    best = None
    best_rank = None
    for (axis, label, _), levels in groups.items():
        field = axis[-1]
        lo, hi = ranges[axis]
        for v1, v2 in pairwise(sorted(levels)):
            first, second = levels[v1], levels[v2]
            if len(first) != 1 or len(second) != 1 or first.keys() == second.keys():
                continue  # Also excludes repeated settings with contradictory verdicts.
            if True in first:
                passing, failing = first[True], second[False]
                pass_value, fail_value = v1, v2
            else:
                passing, failing = second[True], first[False]
                pass_value, fail_value = v2, v1
            pass_index, passed = passing
            fail_index, failed = failing
            same_suite = passed["suite_id"] == failed["suite_id"]
            # Normalize across different units and break ties by proximity in the saved campaign.
            rank = (-passed["project_revision"], (v2 - v1) / (hi - lo), not same_suite,
                    abs(passed["ordinal"] - failed["ordinal"]) if same_suite else 0,
                    max(pass_index, fail_index), min(pass_index, fail_index), field)
            if best_rank is not None and rank >= best_rank:
                continue
            best_rank = rank
            best = {"project_revision": passed["project_revision"], "field": field, "label": label,
                    "suite_id": passed["suite_id"] if same_suite else None,
                    "left": _condition(passed, field, pass_value, True),
                    "right": _condition(failed, field, fail_value, False)}
    return {"pair": best, "inspected": len(rows), "search_limit": SEARCH_LIMIT}
