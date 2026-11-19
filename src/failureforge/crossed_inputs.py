"""Build bounded two-factor test suites against a single saved project revision."""
from itertools import product
from typing import Annotated

from pydantic import Field, FiniteFloat

from .campaign_coverage import coverage_factor_labels, flatten_controls
from .project_bindings import resolve_bindings
from .project_runs import MAX_SUITE_TESTS, ProjectTest, Revision, project_adapters
from .project_solver import MODELS
from .projects import IntakeModel


class CrossedAxis(IntakeModel):
    field: str = Field(min_length=1, max_length=108)
    values: list[Annotated[FiniteFloat, Field(strict=True)]] = Field(min_length=2, max_length=MAX_SUITE_TESTS // 2)


class CrossedCampaign(ProjectTest, Revision):
    label: str = Field(min_length=1, max_length=100)
    axes: tuple[CrossedAxis, CrossedAxis]


def crossed_coordinates(axes, reference):
    fields = [axis["field"] for axis in axes]
    pairs = product(*(axis["values"] for axis in axes))
    points = [dict(zip(fields, pair, strict=True)) for pair in pairs]
    return sorted(points, key=lambda point: point != reference)


def crossed_design(spec):
    controls = flatten_controls(spec.inputs)
    return {**spec.model_dump(mode="json"), "reference": {axis.field: controls[axis.field] for axis in spec.axes}}


def crossed_tests(spec, snapshot):
    if spec.adapter not in {item["id"] for item in project_adapters(snapshot)}:
        raise ValueError("Choose a model available on this project revision")
    a, b = spec.axes
    if a.field == b.field:
        raise ValueError("Choose two different model inputs")
    if len(a.values) * len(b.values) > MAX_SUITE_TESTS:
        raise ValueError(f"A crossed campaign supports up to {MAX_SUITE_TESTS} combinations")
    controls = flatten_controls(spec.inputs)
    allowed = coverage_factor_labels(spec.adapter, controls)
    for axis in spec.axes:
        invalid_target = (axis.field.startswith("targets.") and
                          (not isinstance(spec.inputs.get("targets"), dict)
                           or axis.field.removeprefix("targets.") not in spec.inputs["targets"]))
        if invalid_target or axis.field not in allowed or axis.field in spec.bindings:
            raise ValueError(f"{axis.field} must be a supported, unbound physical input")
        if any(first >= second for first, second in zip(axis.values, axis.values[1:])):
            raise ValueError(f"{axis.field} levels must increase strictly")
        reference = controls.get(axis.field)
        if type(reference) not in (int, float) or reference not in axis.values:
            raise ValueError(f"Include the numeric reference for {axis.field} among its levels")

    design = crossed_design(spec)
    points = crossed_coordinates(design["axes"], design["reference"])
    tests = []
    for index, point in enumerate(points, start=1):
        inputs = spec.inputs.copy()
        for field, value in point.items():
            if field.startswith("targets."):
                joint = field.removeprefix("targets.")
                inputs["targets"] = {**inputs["targets"], joint: value}
            else:
                inputs[field] = value
        role = "reference" if point == design["reference"] else f"cell {index}"
        test = ProjectTest(label=f"{spec.label} · {role}", adapter=spec.adapter, inputs=inputs, bindings=spec.bindings)
        resolved, _ = resolve_bindings(test, snapshot)
        if spec.adapter in ("structural_beam", "thermal_rod"):
            resolved.setdefault("kind", spec.adapter)
        MODELS[spec.adapter].model_validate(resolved)
        tests.append(test)
    return tests
