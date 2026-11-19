"""Target-host execution gates. Calling these functions explicitly runs the robot."""

from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .libero import LiberoRunner
from .profile import digest, json_hash, tree_hashes, write_json

DEFAULT_STATES = tuple(range(12, 22)) + (0, 1)


def _scene_probes(runner: LiberoRunner, root: Path, *, state_id: int = 0, seed: int = 1729) -> dict:
    import numpy as np
    from PIL import Image, ImageDraw

    root.mkdir()
    checks, images = [], []
    reference, _ = runner._reset(state_id, seed)
    baseline_state = runner.settled.copy()
    baseline_pixels = {k: v.copy() for k, v in reference["pixels"].items()}
    baseline_policy = runner._policy_observation(runner._environment_observation(reference))
    baseline_policy_images = {k: baseline_policy[k].detach().cpu().numpy().copy()
        for k in ("observation.images.camera1", "observation.images.camera2")}
    for index, (dx, light) in enumerate((
        (0.0, 1.0), (-0.04, 1.0), (0.04, 1.0), (0.0, 0.7), (0.0, 1.3),
        (-0.04, 0.7), (-0.04, 1.3), (0.04, 0.7), (0.04, 1.3),
    )):
        runner._reset(state_id, seed)
        changed = runner._apply_scene({"main_camera_dx_m": dx, "light_scale": light})
        policy = runner._policy_observation(runner._environment_observation(changed))
        tensor_main = policy["observation.images.camera1"].detach().cpu().numpy()
        tensor_wrist = policy["observation.images.camera2"].detach().cpu().numpy()
        main_delta = float(np.max(np.abs(tensor_main - baseline_policy_images["observation.images.camera1"])))
        wrist_delta = float(np.max(np.abs(tensor_wrist - baseline_policy_images["observation.images.camera2"])))
        physical_equal = bool(np.allclose(runner.settled, baseline_state, rtol=0, atol=1e-10))
        identity = dx == 0.0 and light == 1.0
        healthy = all(v.shape == (256, 256, 3) and v.dtype == np.uint8 and float(v.std()) > 1.0 for v in changed["pixels"].values())
        correct_effect = (main_delta == 0.0 and wrist_delta == 0.0) if identity else main_delta > 0.0
        if light == 1.0:
            correct_effect = correct_effect and wrist_delta == 0.0
        check = {"index": index, "main_camera_dx_m": dx, "light_scale": light,
                 "healthy_render": healthy, "same_physical_start": physical_equal,
                 "policy_main_max_abs_delta": main_delta, "policy_wrist_max_abs_delta": wrist_delta,
                 "effect_matches_contract": bool(correct_effect), "passed": bool(healthy and physical_equal and correct_effect)}
        checks.append(check)
        for name, pixel_key in (("main", "image"), ("wrist", "image2")):
            image = Image.fromarray(np.ascontiguousarray(changed["pixels"][pixel_key][::-1, ::-1]))
            filename = f"probe-{index:02d}-{name}.png"
            image.save(root / filename)
            images.append((f"{index}: {name} dx={dx:+.2f} light={light:.1f}", image))
        write_json(root / f"probe-{index:02d}.json", {"check": check, "scene": runner.scene_evidence})
    after, _ = runner._reset(state_id, seed)
    after = runner._apply_scene({"main_camera_dx_m": 0.0, "light_scale": 1.0})
    reset_isolated = bool(np.allclose(runner.settled, baseline_state, rtol=0, atol=1e-10)
        and all(np.array_equal(after["pixels"][k], baseline_pixels[k]) for k in baseline_pixels))
    checks.append({"name": "changed_then_reference_reset_isolation", "passed": reset_isolated})
    sheet = Image.new("RGB", (6 * 256, 3 * 284), "#111827")
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(images):
        x, y = (index % 6) * 256, (index // 6) * 284
        sheet.paste(image, (x, y + 28))
        draw.text((x + 4, y + 6), label, fill="white")
    sheet.save(root / "scene-contact-sheet.png")
    return {"passed": all(c["passed"] for c in checks), "checks": checks, "static_scene_resets": 11,
            "target_visibility_review": "pending",
            "review_instructions": "Inspect all main/wrist views for the bowl and plate, camera orientation, occlusion, clipping, and meaningful illumination. Automated pixel differences do not establish target visibility."}


def qualify(output_root: Path, *, model_path: Path, renderer: str = "egl",
            state_ids: Iterable[int] = DEFAULT_STATES, seed: int = 1729) -> dict:
    """Execute exactly ten qualification + two search references, and static scene probes.

    No trials are replaced after failures. Every attempt and exception is retained.
    `qualified` denotes automatic checks; live execution additionally requires scene review.
    """
    states = list(state_ids)
    if len(states) != 12 or len(set(states)) != 12 or any(type(s) is not int or s < 0 for s in states):
        raise ValueError("Qualification needs twelve distinct nonnegative initial states: ten screen + two search")
    if set(states).intersection(range(2, 12)):
        raise ValueError("Qualification/search states must exclude the untouched confirmation bank 2..11")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise ValueError("Qualification output directory must be empty to retain immutable evidence")
    started = time.perf_counter()
    report = {"schema_version": "1.0", "protocol": "qualification-v1", "qualified": False,
        "scene_review_approved": False, "state_ids": states, "qualification_state_ids": states[:10],
        "search_state_ids": states[10:], "confirmation_state_ids": list(range(2, 12)), "seed": seed,
        "policy_seed_rule": "seed + state_id", "attempts": [], "failures": [], "checks": {},
        "created_at": datetime.now(timezone.utc).isoformat()}
    runner = LiberoRunner(model_path, renderer)
    try:
        runner._load()
        report["environment_fingerprint"] = runner.fingerprint
        report["environment"] = runner.environment
        write_json(output_root / "qualification.json", report)
        for state_id in states:
            request = {"state_id": state_id, "seed": seed + state_id, "scene_change": {"main_camera_dx_m": 0.0, "light_scale": 1.0},
                       "max_steps": 280, "control_hz": 20}
            directory = output_root / f"reference-{state_id:03d}"
            attempt = {"state_id": state_id, "seed": seed + state_id, "path": directory.name, "status": "running"}
            report["attempts"].append(attempt)
            report["attempted_episodes"] = len(report["attempts"])
            write_json(output_root / "qualification.json", report)
            try:
                result = runner.run(request, directory)
                attempt.update(status="completed", result=result)
                report["environment_fingerprint"] = runner.fingerprint
            except Exception as exc:
                attempt.update(status="infrastructure_error", error=f"{type(exc).__name__}: {exc}")
                report["failures"].append(f"Reference state {state_id}: {exc}")
                # A poisoned CUDA/render context is not reused after infrastructure failure.
                break
            write_json(output_root / "qualification.json", report)
        successes = {a["state_id"] for a in report["attempts"] if a.get("result", {}).get("task_success")}
        report["checks"]["reference_qualification"] = {"successes": len(successes.intersection(states[:10])),
            "required": 8, "denominator": 10, "passed": len(successes.intersection(states[:10])) >= 8}
        report["checks"]["search_references"] = {"state_ids": states[10:], "passed": set(states[10:]).issubset(successes)}
        if not report["failures"]:
            report["checks"]["scene_probes"] = _scene_probes(runner, output_root / "scene-probes", state_id=states[10], seed=seed + states[10])
        report["qualified"] = len(report["attempts"]) == 12 and not report["failures"] and all(
            c["passed"] for c in report["checks"].values())
        report["evidence_sha256"] = tree_hashes(output_root)
        report["evidence_sha256"].pop("qualification.json", None)
    except Exception as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
    finally:
        try:
            runner.close()
        except Exception as exc:
            report["failures"].append(f"Runtime cleanup: {exc}")
            report["qualified"] = False
        report["elapsed_seconds"] = time.perf_counter() - started
        report["attempted_episodes"] = len(report["attempts"])
        report["completed_episodes"] = sum("result" in a for a in report["attempts"])
        write_json(output_root / "qualification.json", report)
    return report


def approve_scene_review(report_path: Path, *, reviewer: str = "local operator") -> dict:
    """Explicit local operator attestation after inspecting actual probe images."""
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("qualified") or not report.get("checks", {}).get("scene_probes", {}).get("passed"):
        raise ValueError("Automatic qualification must pass before scene review can be approved")
    for relative, expected in report["evidence_sha256"].items():
        path = (report_path.parent / relative).resolve()
        if not path.is_relative_to(report_path.parent.resolve()) or not path.is_file() or digest(path) != expected:
            raise ValueError(f"Qualification evidence changed or is missing: {relative}")
    report["scene_review_approved"] = True
    report["scene_review"] = {"reviewer": reviewer, "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "evidence_hash": json_hash(report["evidence_sha256"]),
        "attestation": "Reviewed actual main/wrist probe images: target visibility, orientation, occlusion, clipping and illumination are acceptable throughout the declared domain."}
    write_json(report_path, report)
    return report
