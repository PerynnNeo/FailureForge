"""Finite measured reduction; failures need not be monotonic in scene changes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .planner import AXES, REFERENCE, canonical_scene, scene_key, scene_rank, validate_domain

REDUCTION_VERSION = "bounded-grid-v1"


def preserves_witness(outcomes: Mapping[int | str, str], failing_state_ids: Sequence[int]) -> bool:
    return bool(failing_state_ids) and all(
        outcomes.get(state, outcomes.get(str(state))) in {"horizon_exhausted", "terminated_without_success"} for state in failing_state_ids
    )


class ReductionPlanner:
    """A declared finite grid of up to 12 distinct smaller configurations.

    Coordinate removal comes first, then joint coarse contractions in ascending
    size, then contractions of either retained single axis. Each is measured even if a smaller one
    succeeded, avoiding binary-search assumptions on a nonmonotonic surface.
    No global minimum is claimed.
    """

    def __init__(self, original: Mapping[str, float], domain: Mapping[str, Sequence[float]]):
        self.original = canonical_scene(original)
        self.domain = validate_domain(domain)
        self.original_rank = scene_rank(self.original, self.domain)

    def proposals(self) -> list[dict[str, Any]]:
        factors = [(0.0, 1.0), (1.0, 0.0), (0.0, 0.0), (0.25, 0.25), (0.5, 0.5), (0.75, 0.75),
                   (0.25, 0.0), (0.5, 0.0), (0.75, 0.0), (0.0, 0.25), (0.0, 0.5), (0.0, 0.75)]
        seen = {scene_key(self.original)}
        result = []
        for grid_index, factor in enumerate(factors):
            scene = canonical_scene({axis: REFERENCE[axis] + factor[i] * (self.original[axis] - REFERENCE[axis]) for i, axis in enumerate(AXES)})
            key = scene_key(scene)
            if key in seen or scene_rank(scene, self.domain) >= self.original_rank:
                continue
            seen.add(key)
            result.append({"index": len(result), "scene_change": scene, "reason": f"{REDUCTION_VERSION}:grid={grid_index}"})
        return result

    def is_improvement(self, proposal: Mapping[str, float], incumbent: Mapping[str, float]) -> bool:
        return scene_rank(proposal, self.domain) < scene_rank(incumbent, self.domain)
