"""Engineering review of conditions by operating phase and their one-control tests."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt, model_validator


RecordId = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]
ControlValue = StrictInt | Annotated[FiniteFloat, Field(strict=True)]


class PhaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def phase_fields(adapter):
    from .campaign_coverage import coverage_factor_labels
    from .project_sweeps import FIELDS

    if adapter in FIELDS:
        return dict(FIELDS[adapter])
    return coverage_factor_labels(adapter, ())


class ConditionTest(PhaseModel):
    adapter: Literal["structural_beam", "thermal_rod", "robot_motion", "packaging_lift", "packaging_lift_timed_v2"]
    field: str = Field(min_length=1, max_length=108)
    reference_inputs: dict = Field(min_length=1, max_length=60)
    changed_value: ControlValue

    def pair(self):
        """Validate the actual two solver requests, preserving the operator's literal inputs."""
        from .project_solver import MODELS

        base = self.reference_inputs
        changed = dict(base)
        if self.adapter == "robot_motion" and self.field.startswith("targets."):
            key = self.field.removeprefix("targets.")
            targets = base.get("targets")
            if not isinstance(targets, dict) or key not in targets:
                raise ValueError("Choose a joint target present in the reference inputs")
            original = targets[key]
            changed["targets"] = {**targets, key: self.changed_value}
        else:
            if self.field not in phase_fields(self.adapter) or self.field == "targets.*":
                raise ValueError("Select a physical control supported by this adapter")
            original = base.get(self.field)
            changed[self.field] = self.changed_value
        if type(original) not in (int, float) or original == self.changed_value:
            raise ValueError("Supply an explicit numeric reference and a different comparison value")
        for raw in (base, changed):
            prepared = dict(raw)
            if self.adapter in ("structural_beam", "thermal_rod"):
                prepared.setdefault("kind", self.adapter)
            model = MODELS[self.adapter].model_validate(prepared)
            if self.adapter == "packaging_lift_timed_v2" and self.field in ("head_onset_ms", "head_duration_ms"):
                if not model.head_force_n:
                    raise ValueError("A timing comparison needs a nonzero head force")
        return base, changed


class PhaseCondition(PhaseModel):
    id: RecordId
    answer: str = Field(min_length=1, max_length=500)
    subject: str = Field(default="", max_length=120)
    question: str = Field(default="", max_length=600)
    status: Literal["modeled", "awaiting_data", "physically_testable", "outside_model"]
    reason: str = Field(min_length=1, max_length=1000)
    next_step: str = Field(min_length=1, max_length=1000)
    test: ConditionTest | None = None

    @model_validator(mode="after")
    def executable_status(self):
        if (self.status == "modeled") != (self.test is not None):
            raise ValueError("A modeled condition needs a saved test; other dispositions must omit it")
        return self


class TaskPhase(PhaseModel):
    id: RecordId
    name: str = Field(min_length=1, max_length=100)
    question: str = Field(default="", max_length=600)
    conditions: list[PhaseCondition] = Field(default_factory=list, max_length=24)


def validate_task_phases(project):
    phase_ids = [p.id for p in project.task_phases]
    conditions = [condition for phase in project.task_phases for condition in phase.conditions]
    if len(set(phase_ids)) != len(phase_ids) or len({c.id for c in conditions}) != len(conditions):
        raise ValueError("Each phase and each condition needs a unique stable ID")
    tests = [c.test for c in conditions if c.test is not None]
    if not tests:
        return
    from .project_runs import project_adapters
    enabled = {entry["id"] for entry in project_adapters(project.model_dump(include={"analysis_type", "robot_source", "robot_template"}))}
    for test in tests:
        if test.adapter not in enabled:
            raise ValueError("The condition's solver adapter is unavailable for this prototype")
        if test.adapter == "robot_motion" and not test.reference_inputs.get("model_asset_id") and project.robot_template != "two_finger_hand_v1":
            raise ValueError("Select a URDF from this project or choose the supported two-finger reference hand")
        test.pair()


def check_phase_assets(phases, assets):
    """Phase tests may only reference assets uploaded to this prototype."""
    from .project_solver import ASSET_FIELDS
    available = {asset["id"]: asset for asset in assets}
    for phase in phases:
        for condition in phase.conditions:
            if condition.test is None or condition.test.adapter != "robot_motion":
                continue
            for field in ("model_asset_id", "controller_asset_id"):
                asset_id = condition.test.reference_inputs.get(field)
                if asset_id is None:
                    continue
                asset = available.get(asset_id)
                kind, extension = ASSET_FIELDS[field]
                if not asset or asset["kind"] != kind or Path(asset["filename"]).suffix.lower() != extension:
                    raise ValueError(f"Select this project's own {kind} {extension} file for {field}")
