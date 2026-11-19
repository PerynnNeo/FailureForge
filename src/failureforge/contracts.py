"""Versioned, finite and bounded public experiment contracts."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

SCHEMA_VERSION = "1.0"
POLICY_REVISION = "a24f1f380461b665158d52acd140152c79e8b36d"
TASK_NAME = "pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate"
VALID_OUTCOMES = {"success", "horizon_exhausted", "terminated_without_success"}
ERROR_OUTCOMES = {"load_error", "renderer_error", "model_error", "numerical_error", "worker_lost", "artifact_error"}
TERMINAL_JOBS = {"succeeded", "failed", "cancelled", "interrupted"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def config_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SceneChange(Contract):
    main_camera_dx_m: FiniteFloat = Field(default=0.0, ge=-0.04, le=0.04)
    light_scale: FiniteFloat = Field(default=1.0, ge=0.7, le=1.3)


class Domain(Contract):
    main_camera_dx_m: tuple[FiniteFloat, FiniteFloat] = (-0.04, 0.04)
    light_scale: tuple[FiniteFloat, FiniteFloat] = (0.7, 1.3)

    @model_validator(mode="after")
    def valid_bounds(self):
        for name, minimum, reference, maximum in [
            ("main_camera_dx_m", -0.04, 0.0, 0.04), ("light_scale", 0.7, 1.0, 1.3)
        ]:
            low, high = getattr(self, name)
            if not minimum <= low <= reference <= high <= maximum or low >= high:
                raise ValueError(f"{name} must be ordered within [{minimum}, {maximum}] and contain {reference}")
            if high - low < 1e-8:
                raise ValueError(f"{name} must span at least 0.00000001 to preserve proposal resolution")
        return self


StateId = Annotated[int, Field(strict=True, ge=0, le=9999)]


class CampaignSpec(Contract):
    schema_version: Literal["1.0"] = "1.0"
    name: str = Field(default="Visual robustness campaign", min_length=1, max_length=100)
    backend: Literal["synthetic", "libero"] = "libero"
    method: Literal["random", "sobol", "sobol_local_mix"] = "sobol_local_mix"
    candidate_count: Literal[8, 16, 32] = 32
    seed: int = Field(default=1729, strict=True, ge=0, le=2**31 - 1)
    domain: Domain = Field(default_factory=Domain)
    state_ids: list[StateId] = Field(default_factory=lambda: [0, 1], min_length=2, max_length=2)
    confirmation_state_ids: list[StateId] = Field(default_factory=lambda: list(range(2, 12)), min_length=10, max_length=10)

    @model_validator(mode="after")
    def state_banks(self):
        states = self.state_ids + self.confirmation_state_ids
        if len(set(states)) != len(states):
            raise ValueError("Search and confirmation states must be unique and disjoint")
        if not self.name.strip():
            raise ValueError("Campaign name cannot be blank")
        return self

    def budget_limits(self) -> dict:
        # Baseline screening is explicitly additional to the guide's campaign.
        return {"baseline": 2, "search": 2 * self.candidate_count,
                "reduction": 32, "confirmation": 20, "rerun": 0,
                "infrastructure_retries": 2, "max_attempts": 2 * self.candidate_count + 56}


class RerunRequest(Contract):
    allowance: Literal[2] = 2


def catalog() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "task": {"name": TASK_NAME, "suite": "libero_spatial", "id": 2, "task_order_index": 0},
        "policy": {"repo_id": "lerobot/smolvla_libero", "revision": POLICY_REVISION, "n_action_steps": 50},
        "simulation": {"control_hz": 20, "max_control_steps": 280, "image_size": [256, 256]},
        "domain": Domain().model_dump(mode="json"),
        "methods": ["random", "sobol", "sobol_local_mix"],
        "candidate_counts": [8, 16, 32],
        "synthetic_notice": "Synthetic validation exercises software only. It is not robot evidence.",
    }
