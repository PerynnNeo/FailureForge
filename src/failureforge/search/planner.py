"""Search proposals are pure functions of the seed and persisted history.

We generate a full scrambled 32-point Sobol pool, including for shorter runs.
Local proposals use independent per-index random streams. A proposal is persisted
before execution; resuming always uses that saved value, never a new sample.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
import math

import numpy as np
from scipy.stats import qmc

AXES = ("main_camera_dx_m", "light_scale")
REFERENCE = {"main_camera_dx_m": 0.0, "light_scale": 1.0}
ZERO_TOLERANCE = 1e-10
SEARCH_VERSION = "search-v1"
DEFAULT_DOMAIN = {"main_camera_dx_m": [-0.04, 0.04], "light_scale": [0.7, 1.3]}


def canonical_scene(scene: Mapping[str, float]) -> dict[str, float]:
    result = {key: round(float(scene[key]), 12) for key in AXES}
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError("Scene parameters must be finite")
    return result


def scene_key(scene: Mapping[str, float]) -> tuple[float, float]:
    canonical = canonical_scene(scene)
    return canonical[AXES[0]], canonical[AXES[1]]


def validate_domain(domain: Mapping[str, Sequence[float]]) -> dict[str, list[float]]:
    resolved = {}
    for axis in AXES:
        bounds = list(map(float, domain[axis]))
        if len(bounds) != 2 or not all(math.isfinite(x) for x in bounds):
            raise ValueError(f"Invalid bounds for {axis}")
        if bounds[0] >= bounds[1] or not bounds[0] <= REFERENCE[axis] <= bounds[1]:
            raise ValueError(f"Domain for {axis} must be ordered and contain the reference")
        if bounds[1] - bounds[0] < 1e-8:
            raise ValueError(f"Domain for {axis} must span at least 1e-8 to preserve proposal resolution")
        resolved[axis] = bounds
    if resolved["light_scale"][0] <= 0:
        raise ValueError("Lighting scale must be positive")
    return resolved


def scene_rank(scene: Mapping[str, float], domain: Mapping[str, Sequence[float]]) -> tuple[int, float]:
    """Lexicographic simplicity then directional, normalized L-infinity size."""
    domain = validate_domain(domain)
    magnitudes = []
    for axis in AXES:
        delta = float(scene[axis]) - REFERENCE[axis]
        if abs(delta) <= ZERO_TOLERANCE:
            magnitudes.append(0.0)
            continue
        scale = (domain[axis][1] - REFERENCE[axis]) if delta > 0 else (REFERENCE[axis] - domain[axis][0])
        if scale <= 0:
            raise ValueError("Scene change lies outside its declared domain")
        magnitudes.append(abs(delta) / scale)
    return sum(value > 0 for value in magnitudes), round(max(magnitudes), 12)


def _index(candidate: Mapping[str, Any]) -> int:
    return int(candidate.get("index", candidate.get("proposal_index", 0)))


def _failure_count(candidate: Mapping[str, Any]) -> float:
    score = candidate.get("score")
    if isinstance(score, Mapping):
        return float(score.get("failure_count", score.get("failures", 0)))
    return float(score or 0)


def select_witness(candidates: Sequence[Mapping[str, Any]], domain: Mapping[str, Sequence[float]]) -> Mapping[str, Any] | None:
    eligible = [item for item in candidates if item.get("status") == "completed" and _failure_count(item) > 0]
    if not eligible:
        return None
    return min(eligible, key=lambda item: (-_failure_count(item), *scene_rank(item["scene_change"], domain), _index(item)))


class SearchPlanner:
    """Uniform random, scrambled Sobol, and a Sobol/local Gaussian mixture."""

    def __init__(self, method: str, seed: int, domain: Mapping[str, Sequence[float]] | None = None):
        self.method = {"uniform_random": "random", "adaptive": "local_mix", "adaptive_local": "local_mix", "sobol_local_mix": "local_mix"}.get(method, method)
        if self.method not in {"random", "sobol", "local_mix"}:
            raise ValueError(f"Unknown search method: {method}")
        if seed < 0:
            raise ValueError("Search seed must be nonnegative")
        self.seed = int(seed)
        self.domain = validate_domain(domain or DEFAULT_DOMAIN)
        self.pool = qmc.Sobol(d=2, scramble=True, seed=self.seed).random_base2(m=5)
        self.lower = np.array([self.domain[axis][0] for axis in AXES])
        self.width = np.array([self.domain[axis][1] - self.domain[axis][0] for axis in AXES])

    def _rng(self, index: int, stream: int) -> np.random.Generator:
        return np.random.default_rng(np.random.SeedSequence([self.seed, 1, index, stream]))

    def _scene(self, unit: np.ndarray) -> dict[str, float]:
        return canonical_scene(dict(zip(AXES, self.lower + self.width * unit)))

    def propose(self, index: int, history: Sequence[Mapping[str, Any]]) -> tuple[dict[str, float], str]:
        if not 0 <= index < 32:
            raise ValueError("Proposal index must be between 0 and 31")
        saved = next((row for row in history if _index(row) == index), None)
        if saved is not None:
            return canonical_scene(saved["scene_change"]), str(saved.get("reason", "persisted"))
        prior = sorted((row for row in history if _index(row) < index), key=_index)
        if len(prior) != index or any(row.get("status") != "completed" for row in prior):
            raise ValueError("Every earlier proposal must be persisted and completed")
        seen = {scene_key(row["scene_change"]) for row in prior}
        if self.method == "random":
            rng = self._rng(index, 0)
            for rejection in range(64):
                scene = self._scene(rng.uniform(0, 1, size=2))
                if scene_key(scene) not in seen:
                    return scene, f"uniform_random:rejections={rejection}"
            raise RuntimeError("Random proposal duplicate limit exhausted")
        if self.method == "sobol" or index < 16:
            return self._scene(self.pool[index]), f"sobol_global:{index}"

        parents = [row for row in prior if _failure_count(row) > 0]
        if parents and self._rng(index, 1).random() < 0.5:
            rng = self._rng(index, 2)
            parent = parents[int(rng.integers(len(parents)))]
            center = (np.array([parent["scene_change"][axis] for axis in AXES]) - self.lower) / self.width
            for rejection in range(64):
                unit = center + rng.normal(0.0, 0.10, size=2)
                if np.any(unit < 0) or np.any(unit > 1):
                    continue
                scene = self._scene(unit)
                if scene_key(scene) not in seen:
                    return scene, f"local_gaussian:parent={_index(parent)}:sigma=0.10:rejections={rejection}"
            prefix = "local_fallback:"
        else:
            prefix = ""
        # Consume the next unseen global pool entry, independently of local count.
        for pool_index, unit in enumerate(self.pool):
            scene = self._scene(unit)
            if scene_key(scene) not in seen:
                return scene, f"{prefix}sobol_global:{pool_index}"
        raise RuntimeError("Sobol pool exhausted")
