"""Pinned LIBERO/SmolVLA compatibility boundary; no robotics imports at module import.

All access to upstream private simulator fields is deliberately isolated here.
Infrastructure exceptions propagate; they are never converted into robot failures.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import math
import os
import random
import signal
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from .profile import (ADAPTER_VERSION, POLICY_REPO, POLICY_REVISION, TASK_ID, TASK_NAME, TASK_SUITE,
                      digest, doctor, json_hash, source_identity, verify_bootstrap, write_json)
from .recording import EpisodeRecorder


class SimulationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_request(request: dict) -> dict:
    """Validate again at the process boundary before allocation or package imports."""
    state_id, seed = request.get("state_id"), request.get("seed")
    if type(state_id) is not int or state_id < 0 or type(seed) is not int or not 0 <= seed < 2**32:
        raise SimulationError("invalid_scene", "state_id must be nonnegative and seed a uint32 integer")
    max_steps, hz = request.get("max_steps", 280), request.get("control_hz", 20)
    if type(max_steps) is not int or not 1 <= max_steps <= 280 or hz != 20:
        raise SimulationError("invalid_scene", "Supported horizon is 1..280 steps at 20 Hz")
    change = request.get("scene_change", {})
    dx, light = change.get("main_camera_dx_m", 0.0), change.get("light_scale", 1.0)
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (dx, light)):
        raise SimulationError("invalid_scene", "Scene parameters must be finite numbers")
    if not -0.04 <= dx <= 0.04 or not 0.7 <= light <= 1.3:
        raise SimulationError("invalid_scene", "Scene parameters exceed the supported approved domain")
    return {**request, "state_id": state_id, "seed": seed, "max_steps": max_steps, "control_hz": hz,
            "scene_change": {"main_camera_dx_m": float(dx), "light_scale": float(light)}}


def batch_observation(observation: dict) -> dict:
    """Batch every nested state leaf, including the quaternion, not only images."""
    import numpy as np
    result = {}
    for key, value in observation.items():
        if isinstance(value, dict):
            result[key] = batch_observation(value)
        else:
            if value is None:
                raise SimulationError("numerical_error", f"Missing observation field: {key}")
            array = np.asarray(value)
            if array.dtype.kind not in "buif" or not np.isfinite(array).all():
                raise SimulationError("numerical_error", f"Non-finite/non-numeric observation field: {key}")
            result[key] = np.ascontiguousarray(array[None, ...])
    return result


@contextlib.contextmanager
def reset_deadline(seconds: int = 120):
    """Best-effort Python timeout; the parent watchdog handles swallowed/native hangs."""
    if not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        raise SimulationError("load_error", "Run the simulator on the main thread of a Linux worker process")
    previous = signal.getsignal(signal.SIGALRM)
    def timeout(signum, frame):
        raise SimulationError("renderer_error", f"Environment reset exceeded {seconds}s")
    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class LiberoRunner:
    def __init__(self, model_path: Path, renderer: str = "egl", qualification_path: Path | None = None):
        if renderer not in ("egl", "glfw", "osmesa"):
            raise ValueError("Renderer must be egl, glfw or osmesa")
        self.model_path = Path(model_path).resolve()
        self.renderer = renderer
        self.qualification_path = Path(qualification_path) if qualification_path else None
        self._loaded = False
        self._env = None
        self.load_seconds = 0.0
        self._verified_qualification_hash = None

    def _load(self) -> None:
        if self._loaded:
            return
        started = time.perf_counter()
        report = doctor(self.model_path)
        if not report["profile_compatible"]:
            raise SimulationError("load_error", "; ".join(report["failures"]))
        # Both are set before importing torch/transformers or simulator modules.
        os.environ["MUJOCO_GL"] = self.renderer
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        try:
            bootstrap = verify_bootstrap(self.model_path)
            if bootstrap.get("libero_config_dir"):
                os.environ.setdefault("LIBERO_CONFIG_PATH", bootstrap["libero_config_dir"])
            config_path = Path(os.environ.get("LIBERO_CONFIG_PATH", str(Path.home() / ".libero"))) / "config.yaml"
            if not config_path.is_file():
                raise RuntimeError("Missing LIBERO config; run scripts/bootstrap_robotics.py first")
            import numpy as np
            import torch
            import lerobot.envs.libero as upstream
            from libero.libero import benchmark, get_libero_path
            from lerobot.configs import PreTrainedConfig
            from lerobot.envs.configs import LiberoEnv as LiberoConfig
            from lerobot.envs.utils import preprocess_observation
            from lerobot.policies.factory import make_pre_post_processors
            from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
            from robosuite.utils import binding_utils

            self.np, self.torch = np, torch
            self._upstream = upstream
            effective_renderer = {"egl_context": "egl", "osmesa_context": "osmesa", "glfw_context": "glfw"}.get(
                binding_utils.GLContext.__module__.split(".")[-1], "unknown")
            if effective_renderer != self.renderer:
                raise RuntimeError(f"Requested renderer {self.renderer}, but robosuite selected {effective_renderer}; use a compatible renderer profile")
            source = source_identity(Path(upstream.__file__).resolve())
            source["hf_libero_wrapper_sha256"] = digest(Path(inspect.getfile(upstream.OffScreenRenderEnv)))
            source["libero_config_sha256"] = digest(config_path)
            cuda_report = doctor(cuda=True)
            if cuda_report["cuda_test"] != "passed":
                raise RuntimeError(cuda_report.get("cuda_error", "CUDA operation failed"))
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True
            self.suite = benchmark.get_benchmark_dict()[TASK_SUITE](task_order_index=0)
            task = self.suite.get_task(TASK_ID)
            if task.name != TASK_NAME:
                raise RuntimeError(f"Task identity mismatch: task {TASK_ID} is {task.name}")
            bddl = Path(get_libero_path("bddl_files")) / task.problem_folder / task.bddl_file
            init_file = Path(get_libero_path("init_states")) / task.problem_folder / Path(task.init_states_file).name
            if Path(get_libero_path("assets")).resolve() != Path(bootstrap["assets"]["path"]).resolve():
                raise RuntimeError("LIBERO config assets path differs from the verified bootstrap snapshot")
            self.task_identity = {"suite": TASK_SUITE, "task_id": TASK_ID, "task_order_index": 0,
                "name": task.name, "language": task.language, "bddl_sha256": digest(bddl),
                "initial_state_file_sha256": digest(init_file)}
            config = PreTrainedConfig.from_pretrained(str(self.model_path), local_files_only=True)
            if config.type != "smolvla" or config.n_action_steps != 50 or config.chunk_size != 50:
                raise RuntimeError("Checkpoint must use SmolVLA with chunk_size=n_action_steps=50")
            if getattr(config, "compile_model", False) or getattr(config, "adapt_to_pi_aloha", False):
                raise RuntimeError("Unexpected policy compilation or ALOHA action adaptation")
            dependencies = bootstrap["dependencies"]
            vlm_dependency = dependencies[config.vlm_model_name]
            config.vlm_model_name = vlm_dependency["path"]
            config.device, config.use_amp = "cuda", False
            self.policy = SmolVLAPolicy.from_pretrained(str(self.model_path), config=config, local_files_only=True, strict=True)
            self.policy.to("cuda").eval()
            overrides = {"device_processor": {"device": "cuda"}}
            tokenizer_repo = bootstrap.get("tokenizer_repo")
            if tokenizer_repo:
                overrides["tokenizer_processor"] = {"tokenizer_name": dependencies[tokenizer_repo]["path"]}
            self.preprocessor, self.postprocessor = make_pre_post_processors(config, pretrained_path=str(self.model_path),
                preprocessor_overrides=overrides)
            env_config = LiberoConfig(task=TASK_SUITE, task_ids=[TASK_ID], obs_type="pixels_agent_pos",
                observation_height=256, observation_width=256, fps=20, hard_reset=True, control_mode="relative")
            self.env_preprocessor, self.env_postprocessor = env_config.get_env_processors()
            self.preprocess_observation = preprocess_observation
            self._env = upstream.LiberoEnv(self.suite, TASK_ID, TASK_SUITE, episode_length=280,
                obs_type="pixels_agent_pos", observation_height=256, observation_width=256,
                init_states=True, hard_reset=True, control_freq=20, control_mode="relative", num_steps_wait=10)
            self.environment = {"schema_version": "1.0", "adapter_version": ADAPTER_VERSION,
                "profile": report, "source": source, "renderer": self.renderer,
                "policy": {"repo_id": POLICY_REPO, "revision": POLICY_REVISION,
                    "snapshot_hash": json_hash(bootstrap["policy"]["sha256"]), "chunk_size": 50, "n_action_steps": 50,
                    "use_amp": False, "device": "cuda", "internal_image_resize": list(config.resize_imgs_with_padding),
                    "parameter_dtypes": sorted({str(p.dtype) for p in self.policy.parameters()})},
                "external_dependencies": {k: {"revision": v["revision"], "files_hash": json_hash(v["sha256"])} for k, v in dependencies.items()},
                "assets": {"revision": bootstrap["assets"]["revision"], "files_hash": json_hash(bootstrap["assets"]["sha256"])},
                "task": self.task_identity, "gpu": cuda_report["gpu"], "gpu_memory_bytes": cuda_report["gpu_memory_bytes"],
                "cuda": cuda_report["cuda"], "nvidia_driver": cuda_report["nvidia_driver"],
                "gpu_compute_capability": cuda_report["gpu_compute_capability"], "cudnn_version": cuda_report["cudnn_version"],
                "implementation_sha256": {name: digest(Path(__file__).parent / name) for name in ("libero.py", "profile.py", "recording.py")},
                "numerics": {"cuda_matmul_tf32": True, "cudnn_tf32": True,
                    "cudnn_benchmark": True, "deterministic_algorithms": torch.are_deterministic_algorithms_enabled()},
                "offline_loading": True, "control_hz": 20, "hard_reset": True, "settle_steps": 10}
            self.fingerprint = json_hash(self.environment)
            self.environment["fingerprint"] = self.fingerprint
            self._loaded = True
            self.load_seconds = time.perf_counter() - started
        except SimulationError:
            raise
        except Exception as exc:
            raise SimulationError("load_error", f"Robotics initialization failed: {exc}") from exc

    def _qualification_gate(self) -> None:
        if self.qualification_path is None:
            return  # explicit diagnostic/qualification caller; worker supplies a gate
        try:
            qualification = json.loads(self.qualification_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SimulationError("load_error", "A completed qualification report is required") from exc
        if not qualification.get("qualified") or not qualification.get("scene_review_approved"):
            raise SimulationError("load_error", "Runtime baseline/scene qualification is incomplete")
        if qualification.get("environment_fingerprint") != self.fingerprint:
            raise SimulationError("load_error", "Environment changed since qualification; requalify this runtime")
        report_hash = json_hash(qualification)
        if report_hash != self._verified_qualification_hash:
            evidence = qualification.get("evidence_sha256", {})
            if not evidence or qualification.get("scene_review", {}).get("evidence_hash") != json_hash(evidence):
                raise SimulationError("load_error", "Scene review does not attest the qualification evidence")
            for relative, expected in evidence.items():
                path = (self.qualification_path.parent / relative).resolve()
                if not path.is_relative_to(self.qualification_path.parent.resolve()) or not path.is_file() or digest(path) != expected:
                    raise SimulationError("load_error", f"Qualification evidence changed: {relative}")
            self._verified_qualification_hash = report_hash

    def _reset(self, state_id: int, seed: int):
        np, torch = self.np, self.torch
        if state_id >= len(self._env._init_states):
            raise SimulationError("invalid_scene", f"Initial state {state_id} is outside installed state inventory")
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        for obj in (self.policy, self.preprocessor, self.postprocessor, self.env_preprocessor, self.env_postprocessor):
            reset = getattr(obj, "reset", None)
            if callable(reset):
                reset()
        self._env.init_state_id = state_id  # upstream increments; reset this on EVERY episode
        benchmark_state = np.asarray(self._env._init_states[state_id], dtype=np.float64).copy()
        with reset_deadline():
            observation, _ = self._env.reset(seed=seed)
        self.raw = self._env._env
        self.sim = self.raw.env.sim
        self.settled = np.asarray(self.sim.get_state().flatten(), dtype=np.float64).copy()
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        self._scene_baseline = {name: getattr(self.sim.model, name).copy() for name in (
            "cam_pos", "cam_quat", "cam_fovy", "cam_bodyid", "cam_mode", "light_ambient", "light_diffuse", "light_specular")}
        self._camera_id = self.sim.model.camera_name2id("agentview")
        self._wrist_id = self.sim.model.camera_name2id("robot0_eye_in_hand")
        if int(self.sim.model.cam_mode[self._camera_id]) != 0:
            raise SimulationError("invalid_scene", "Only fixed agentview camera mode is supported")
        return observation, benchmark_state

    def _apply_scene(self, change: dict):
        np = self.np
        model = self.sim.model
        physical_before = np.asarray(self.sim.get_state().flatten()).copy()
        for name, baseline in self._scene_baseline.items():
            getattr(model, name)[:] = baseline
        model.cam_pos[self._camera_id, 0] = self._scene_baseline["cam_pos"][self._camera_id, 0] + change["main_camera_dx_m"]
        for name in ("light_ambient", "light_diffuse", "light_specular"):
            getattr(model, name)[:] = np.clip(self._scene_baseline[name] * change["light_scale"], 0.0, 1.0)
        self.sim.forward()
        refresh = getattr(self.raw, "regenerate_obs_from_state", None)
        if not callable(refresh):
            raise SimulationError("load_error", "Pinned hf-libero regenerate_obs_from_state hook is unavailable")
        # Use the CURRENT settled state. The benchmark state would undo settling.
        raw_observation = refresh(physical_before)
        physical_after = np.asarray(self.sim.get_state().flatten()).copy()
        if not np.allclose(physical_before, physical_after, rtol=0, atol=1e-12):
            raise SimulationError("invalid_scene", "Visual scene refresh altered the settled physical state")
        if not np.array_equal(model.cam_pos[self._wrist_id], self._scene_baseline["cam_pos"][self._wrist_id]):
            raise SimulationError("invalid_scene", "Scene change moved the wrist camera")
        if not np.isclose(model.cam_pos[self._camera_id, 0], self._scene_baseline["cam_pos"][self._camera_id, 0] + change["main_camera_dx_m"]):
            raise SimulationError("invalid_scene", "Camera edit did not survive observation regeneration")
        observation = self._env._format_raw_obs(raw_observation)
        self.scene_evidence = {"schema_version": "1.0", "requested": change,
            "camera": "agentview", "camera_id": self._camera_id, "parent_body_id": int(model.cam_bodyid[self._camera_id]),
            "displacement_frame": "camera parent body", "wrist_camera": "robot0_eye_in_hand",
            "light_names": [model.light_id2name(i) for i in range(model.nlight)], "light_rule": "baseline * scale, clipped to [0,1]",
            "baseline": {k: v.tolist() for k, v in self._scene_baseline.items()},
            "applied": {k: getattr(model, k).tolist() for k in self._scene_baseline}, "physical_state_unchanged": True}
        return observation

    def _environment_observation(self, observation: dict) -> dict:
        batch = self.preprocess_observation(batch_observation(observation))
        batch["task"] = [self.task_identity["language"]]
        batch = self.env_preprocessor(batch)
        state = batch["observation.state"]
        if tuple(state.shape) != (1, 8) or not self.torch.isfinite(state).all():
            raise SimulationError("numerical_error", "Environment processor did not return a finite 1x8 state")
        return batch

    def _policy_observation(self, batch: dict) -> dict:
        batch = self.preprocessor(batch)
        for key in ("observation.images.camera1", "observation.images.camera2"):
            image = batch.get(key)
            if image is None or tuple(image.shape) != (1, 3, 256, 256):
                raise SimulationError("model_error", f"Checkpoint camera rename/shape contract violated: {key}")
            if not self.torch.isfinite(image).all() or image.min() < 0 or image.max() > 1:
                raise SimulationError("numerical_error", f"Policy image is outside finite [0,1]: {key}")
        if not self.torch.isfinite(batch["observation.state"]).all():
            raise SimulationError("numerical_error", "Non-finite normalized policy state")
        return batch

    def _physics_layout(self) -> dict:
        model = self.sim.model
        joints = []
        for index in range(model.njnt):
            joints.append({"joint_id": index, "name": model.joint_id2name(index),
                "type": ("free", "ball", "slide", "hinge")[int(model.jnt_type[index])],
                "qpos_start": int(model.jnt_qposadr[index]),
                "qpos_end": int(model.jnt_qposadr[index + 1]) if index + 1 < model.njnt else int(model.nq),
                "qvel_start": int(model.jnt_dofadr[index]),
                "qvel_end": int(model.jnt_dofadr[index + 1]) if index + 1 < model.njnt else int(model.nv)})
        return {"nq": int(model.nq), "nv": int(model.nv), "joints": joints,
            "physics_timestep_seconds": float(model.opt.timestep),
            "coordinate_convention": "MuJoCo qpos/qvel: free joint position xyz + quaternion wxyz; ball quaternion wxyz; hinge radians; slide metres. Joint intervals are half-open.",
            "simulator_state_layout": "[time, qpos[nq], qvel[nv]] (robosuite MjSimState)"}

    def run(self, request: dict, output_dir: Path, cancelled: Callable[[], bool] = lambda: False) -> dict:
        request = validate_request(request)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if any(output_dir.iterdir()):
            raise ValueError("Episode output directory must be empty; attempts are immutable")
        write_json(output_dir / "spec.json", request)
        start = time.perf_counter()
        recorder = None
        phase = "load_error"
        timings = {"load_seconds": 0.0, "reset_seconds": 0.0, "inference_seconds": 0.0, "simulation_seconds": 0.0}
        inference_call_seconds, chunk_starts = [], []
        try:
            already_loaded = self._loaded
            self._load()
            timings["load_seconds"] = 0.0 if already_loaded else self.load_seconds
            write_json(output_dir / "environment.json", self.environment)
            write_json(output_dir / "task_identity.json", {**self.task_identity, "state_id": request["state_id"]})
            phase = "renderer_error"
            reset_start = time.perf_counter()
            observation, benchmark_state = self._reset(request["state_id"], request["seed"])
            observation = self._apply_scene(request["scene_change"])
            timings["reset_seconds"] = time.perf_counter() - reset_start
            physics_layout = self._physics_layout()
            self.environment["physics"] = physics_layout
            self.environment.pop("fingerprint", None)
            self.fingerprint = json_hash(self.environment)
            self.environment["fingerprint"] = self.fingerprint
            # The native simulator is allocated at reset. Include its actual timestep
            # and joint layout in the qualification identity before the first action.
            self._qualification_gate()
            write_json(output_dir / "environment.json", self.environment)
            write_json(output_dir / "task_identity.json", {**self.task_identity, "state_id": request["state_id"],
                "benchmark_state_sha256": hashlib.sha256(benchmark_state.astype("<f8").tobytes()).hexdigest(),
                "settled_state_sha256": hashlib.sha256(self.settled.astype("<f8").tobytes()).hexdigest(),
                "state_hash_encoding": "little-endian float64, C order"})
            self.np.savez_compressed(output_dir / "initial_state.npz", benchmark=benchmark_state,
                settled=self.settled, settled_qpos=self.sim.data.qpos.copy(), settled_qvel=self.sim.data.qvel.copy(),
                state_id=self.np.asarray(request["state_id"], dtype=self.np.int64))
            write_json(output_dir / "scene_change.json", self.scene_evidence)
            recorder = EpisodeRecorder(output_dir, request["control_hz"], physics_layout=physics_layout)
            batch = self._environment_observation(observation)
            task_success = bool(self.raw.check_success())
            recorder.observation(observation["pixels"], batch["observation.state"][0].cpu().numpy(),
                self.sim.get_state().flatten(), float(self.sim.data.time), task_success,
                qpos=self.sim.data.qpos, qvel=self.sim.data.qvel)
            steps, outcome = 0, "horizon_exhausted"
            self.torch.cuda.reset_peak_memory_stats()
            if task_success:
                raise SimulationError("invalid_scene", "Task already succeeds before the first action")
            for step_index in range(request["max_steps"]):
                if cancelled():
                    outcome = "cancelled"
                    break
                phase = "model_error"
                self.torch.cuda.synchronize()
                inference_start = time.perf_counter()
                policy_batch = self._policy_observation(batch)
                queue = getattr(self.policy, "_queues", {}).get("action")
                if queue is not None and len(queue) == 0:
                    chunk_starts.append(step_index)
                with self.torch.inference_mode():
                    action = self.policy.select_action(policy_batch)
                action = self.postprocessor(action)
                action = self.env_postprocessor({"action": action})["action"]
                self.torch.cuda.synchronize()
                call_seconds = time.perf_counter() - inference_start
                inference_call_seconds.append(call_seconds)
                timings["inference_seconds"] += call_seconds
                action_np = action.detach().cpu().numpy()
                if action_np.shape != (1, 7) or not self.np.isfinite(action_np).all():
                    raise SimulationError("numerical_error", "Policy returned an invalid action")
                if cancelled():
                    outcome = "cancelled"
                    break
                phase = "renderer_error"
                simulation_start = time.perf_counter()
                observation, reward, terminated, truncated, info = self._env.step(action_np[0])
                timings["simulation_seconds"] += time.perf_counter() - simulation_start
                if not math.isfinite(float(reward)) or not self.np.isfinite(self.sim.get_state().flatten()).all():
                    raise SimulationError("numerical_error", "Simulator returned non-finite reward or physical state")
                task_success = bool(self.raw.check_success())  # independent primary task predicate
                if bool(info["is_success"]) != task_success:
                    raise SimulationError("numerical_error", "Wrapper success disagrees with the task predicate")
                steps = step_index + 1
                recorder.action(action_np[0], reward, terminated, truncated)
                batch = self._environment_observation(observation)
                recorder.observation(observation["pixels"], batch["observation.state"][0].cpu().numpy(),
                    self.sim.get_state().flatten(), float(self.sim.data.time), task_success,
                    qpos=self.sim.data.qpos, qvel=self.sim.data.qvel)
                if task_success:
                    outcome = "success"
                    break
                if terminated or truncated:
                    outcome = "terminated_without_success"
                    break
            recorder.close()
            timings["video_encoding_seconds"] = recorder.encode_seconds
            result = {"backend": "libero", "outcome": outcome, "steps": steps, "elapsed_seconds": time.perf_counter() - start,
                "task_success": task_success, "metadata": {"engine": "libero", "environment_fingerprint": self.fingerprint,
                    "timings": timings, "peak_cuda_memory_bytes": int(self.torch.cuda.max_memory_allocated()),
                    "state_id": request["state_id"], "seed": request["seed"], "frame_count": len(recorder.frames),
                    "inference_call_seconds": inference_call_seconds, "chunk_start_action_indices": chunk_starts,
                    "first_chunk_includes_warmup": True,
                    "success_predicate": "LIBERO check_success", "recorded_camera_views": ["main", "wrist"]}}
            write_json(output_dir / "outcome.json", result)
            return result
        except Exception as exc:
            if recorder is not None:
                try:
                    recorder.close()
                except Exception:
                    pass  # preserve the original failure; incomplete attempts are not published
            code = exc.code if isinstance(exc, SimulationError) else phase
            write_json(output_dir / "error.json", {"code": code, "message": str(exc), "traceback": traceback.format_exc(),
                "elapsed_seconds": time.perf_counter() - start})
            if isinstance(exc, SimulationError):
                raise
            raise SimulationError(code, str(exc)) from exc

    def close(self) -> None:
        if self._env is not None:
            self._env.close()
            self._env = None
        self._loaded = False
        for name in ("policy", "preprocessor", "postprocessor", "env_preprocessor", "env_postprocessor"):
            if hasattr(self, name):
                delattr(self, name)
