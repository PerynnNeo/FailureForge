"""An explicit software diagnostic backend, never robot evidence.

The response surface deliberately has nonmonotonic failure islands. It exercises
bounded search, paired outcomes, cancellation, numerical artifacts, and fresh
executions on a laptop without downloading weights or creating simulated video.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
import json
import math
import platform
import time

import numpy as np


class SyntheticRunner:
    backend = "synthetic"
    evidence_kind = "synthetic_diagnostic"

    def run(self, request: Mapping[str, Any], output_dir: Path, cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
        started = time.monotonic()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        cancelled = cancelled or (lambda: False)
        state_id, seed = int(request["state_id"]), int(request["seed"])
        scene = request["scene_change"]
        dx, lighting = float(scene["main_camera_dx_m"]), float(scene["light_scale"])
        if not all(math.isfinite(value) for value in (dx, lighting)):
            raise ValueError("Synthetic scene changes must be finite")
        x, light = dx / 0.04, (lighting - 1.0) / 0.30
        rng = np.random.default_rng(np.random.SeedSequence([seed, state_id, 17]))
        reference_failure = state_id % 7 == 6
        severity = max(abs(x), abs(light))
        risk = 0.50 * abs(x) + 0.45 * abs(light) + 0.16 * math.sin(2.5 * math.pi * x) ** 2
        risk += float(rng.uniform(-0.015, 0.015))
        island = 0.40 < x < 0.70 and -0.75 < light < -0.25
        failed = risk > (0.65 + 0.03 * (state_id % 3)) or island
        if reference_failure:
            failed = not (0.15 < severity < 0.55 and dx > 0)
        max_steps = int(request.get("max_steps", 280))
        control_hz = int(request.get("control_hz", 20))
        planned_steps = max_steps if failed else min(max_steps, 36 + state_id % 10)
        trace = []
        was_cancelled = False
        for step in range(planned_steps):
            if cancelled():
                was_cancelled = True
                break
            progress = (step + 1) / max(planned_steps, 1)
            trace.append((progress, math.sin(progress * math.pi) * (1 + abs(x)), lighting))
        steps = len(trace)
        success = not failed and not was_cancelled and steps == planned_steps
        outcome = "cancelled" if was_cancelled else ("success" if success else "horizon_exhausted")
        values = np.asarray(trace, dtype=np.float64).reshape(steps, 3)
        observations = np.vstack((np.array([[0.0, 0.0, lighting]], dtype=np.float64), values))
        np.savez_compressed(
            output_dir / "traces.npz",
            control_step=np.arange(steps, dtype=np.int64),
            timestamps=np.arange(steps + 1, dtype=np.float64) / control_hz,
            diagnostic_state=observations,
            diagnostic_delta=np.diff(observations, axis=0),
            success=np.array([False] * steps + [success], dtype=np.bool_),
        )
        initial = np.array([float(state_id), float(seed), 0.0], dtype=np.float64)
        np.savez_compressed(output_dir / "initial_state.npz", benchmark_state=initial, settled_state=initial.copy(), state_id=np.array(state_id, dtype=np.int64))
        metadata = {
            "backend": self.backend,
            "evidence_kind": self.evidence_kind,
            "notice": "SOFTWARE DIAGNOSTIC ONLY. No robot simulation, model inference, or camera recordings.",
            "algorithm": "nonmonotonic-surface-v1",
            "request": dict(request),
            "timestamp_convention": "Initial observation t=0; control_step i yields observation t=(i+1)/control_hz.",
            "frames_available": False,
            "risk": risk,
        }
        def write_json(name: str, content: Any) -> None:
            (output_dir / name).write_text(json.dumps(content, indent=2, allow_nan=False), encoding="utf-8")

        write_json("spec.json", dict(request))
        write_json("environment.json", {**metadata, "python": platform.python_version(), "platform": platform.system(), "numpy": np.__version__})
        write_json("scene_change.json", {"schema_version": "1.0", "backend": self.backend, "scene_change": dict(scene)})
        write_json("task_identity.json", {"schema_version": "1.0", "task": "nonmonotonic-surface-v1", "backend": self.backend,
                                          "notice": metadata["notice"], "state_id": state_id})
        write_json("frames.json", {"schema_version": "1.0", "fps": control_hz, "frames": [], "available": False,
                                   "notice": "This diagnostic does not render robot cameras.",
                                   "convention": metadata["timestamp_convention"]})
        points = " ".join(f"{20 + i * 460 / max(steps-1,1):.2f},{150 - row[1] * 55:.2f}" for i, row in enumerate(values))
        (output_dir / "diagnostic.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="200" viewBox="0 0 500 200">'
            '<rect width="500" height="200" fill="#101827"/>'
            '<text x="20" y="28" fill="#f6bb73" font-family="sans-serif" font-size="14">SYNTHETIC SOFTWARE DIAGNOSTIC</text>'
            '<text x="20" y="48" fill="#a8b6cb" font-family="sans-serif" font-size="12">Numeric test trace. No robot evidence.</text>'
            f'<polyline points="{points}" fill="none" stroke="#63d5b2" stroke-width="2"/></svg>',
            encoding="utf-8",
        )
        result = {
            "outcome": outcome,
            "task_success": success,
            "steps": steps,
            "elapsed_seconds": time.monotonic() - started,
            "backend": self.backend,
            "evidence_kind": self.evidence_kind,
            "metadata": metadata,
        }
        write_json("outcome.json", result)
        return result

    def close(self) -> None:
        """Mirror the real runner's lifecycle without holding resources."""
