"""CPU checks exercise integration boundaries; GPU tests are explicit and opt-in."""

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from failureforge.simulation import LiberoRunner, SimulationError, approve_scene_review
from failureforge.simulation.libero import batch_observation, validate_request
from failureforge.simulation.profile import digest, json_hash, write_json


REQUEST = {"state_id": 0, "seed": 1729, "scene_change": {"main_camera_dx_m": 0.0, "light_scale": 1.0},
           "max_steps": 3, "control_hz": 20}


def test_import_and_doctor_do_not_import_robotics():
    code = "import sys; from failureforge.simulation import doctor; doctor(); assert not any(k in sys.modules for k in ['torch','libero','mujoco','lerobot'])"
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    subprocess.run([sys.executable, "-c", code], check=True, env=environment)


@pytest.mark.parametrize("change", [{"main_camera_dx_m": float("nan")}, {"light_scale": float("inf")},
    {"main_camera_dx_m": 0.041}, {"light_scale": 0.69}, {"light_scale": True}])
def test_domain_rejected_before_runtime_import(change):
    with pytest.raises(SimulationError, match="Scene parameters"):
        validate_request({**REQUEST, "scene_change": change})


def test_nested_robot_quaternion_is_batched_and_contiguous():
    observation = {"pixels": {"image": np.zeros((256, 256, 3), dtype=np.uint8)},
                   "robot_state": {"eef": {"quat": np.asarray([0., 0., 0., 1.])}}}
    batched = batch_observation(observation)
    assert batched["pixels"]["image"].shape == (1, 256, 256, 3)
    assert batched["robot_state"]["eef"]["quat"].shape == (1, 4)
    assert batched["robot_state"]["eef"]["quat"].flags.c_contiguous
    observation["robot_state"]["eef"]["quat"][0] = np.nan
    with pytest.raises(SimulationError, match="Non-finite"):
        batch_observation(observation)


def scene_runner(tmp_path):
    runner = LiberoRunner(tmp_path)
    runner.np = np
    model = SimpleNamespace(cam_pos=np.asarray([[1., 2., 3.], [4., 5., 6.]]),
        cam_quat=np.asarray([[1., 0., 0., 0.], [1., 0., 0., 0.]]), cam_fovy=np.asarray([45., 45.]),
        cam_bodyid=np.asarray([0, 1]), cam_mode=np.asarray([0, 0]), light_ambient=np.asarray([[.1, .2, .3]]),
        light_diffuse=np.asarray([[.9, .9, .9]]), light_specular=np.asarray([[.2, .2, .2]]),
        nlight=1, light_id2name=lambda i: "light0")
    runner._scene_baseline = {k: v.copy() for k, v in vars(model).items() if isinstance(v, np.ndarray)}
    runner._camera_id, runner._wrist_id = 0, 1
    physical = np.asarray([1., 2., 3.])
    runner.sim = SimpleNamespace(model=model, get_state=lambda: physical.copy(), forward=lambda: None)
    runner.raw = SimpleNamespace(regenerate_obs_from_state=lambda state: {"state": state.copy()})
    runner._env = SimpleNamespace(_format_raw_obs=lambda raw: raw)
    return runner, model, physical


def test_scene_reapply_uses_baseline_and_preserves_current_settled_state(tmp_path):
    runner, model, physical = scene_runner(tmp_path)
    change = {"main_camera_dx_m": .04, "light_scale": 1.3}
    runner._apply_scene(change)
    assert model.cam_pos[0, 0] == pytest.approx(1.04)
    runner._apply_scene(change)
    assert model.cam_pos[0, 0] == pytest.approx(1.04)  # no accumulation
    np.testing.assert_array_equal(model.cam_pos[1], [4., 5., 6.])
    np.testing.assert_array_equal(model.light_diffuse, [[1., 1., 1.]])
    observation = runner._apply_scene({"main_camera_dx_m": 0.0, "light_scale": 1.0})
    np.testing.assert_array_equal(observation["state"], physical)
    np.testing.assert_array_equal(model.light_diffuse, [[.9, .9, .9]])
    assert model.cam_pos[0, 0] == 1.0


def test_scene_refresh_cannot_change_physics(tmp_path):
    runner, _, physical = scene_runner(tmp_path)
    def bad_refresh(state):
        physical[0] += 1
        return {}
    runner.raw.regenerate_obs_from_state = bad_refresh
    with pytest.raises(SimulationError, match="physical state"):
        runner._apply_scene(REQUEST["scene_change"])


def test_exact_state_is_reselected_and_queues_reset_before_every_episode(tmp_path, monkeypatch):
    runner, model, _ = scene_runner(tmp_path)
    calls = []
    runner.torch = SimpleNamespace(manual_seed=lambda seed: None, cuda=SimpleNamespace(manual_seed_all=lambda seed: None))
    runner.policy = SimpleNamespace(reset=lambda: calls.append("policy_reset"))
    runner.preprocessor = SimpleNamespace(reset=lambda: calls.append("preprocessor_reset"))
    runner.postprocessor = runner.env_preprocessor = runner.env_postprocessor = SimpleNamespace(reset=lambda: None)
    model.camera_name2id = lambda name: 0 if name == "agentview" else 1
    raw = SimpleNamespace(env=SimpleNamespace(sim=runner.sim))
    env = SimpleNamespace(_init_states=np.asarray([[0., 0., 0.], [9., 8., 7.]]), init_state_id=99, _env=raw)
    def reset(seed):
        calls.append(("reset", env.init_state_id, seed))
        env.init_state_id += 1
        return {"pixels": {}}, {}
    env.reset = reset
    runner._env = env
    monkeypatch.setattr("failureforge.simulation.libero.reset_deadline", contextlib.nullcontext)
    for _ in range(2):
        _, benchmark = runner._reset(1, 1729)
        np.testing.assert_array_equal(benchmark, [9., 8., 7.])
        np.testing.assert_array_equal(runner.settled, [1., 2., 3.])
    assert calls == ["policy_reset", "preprocessor_reset", ("reset", 1, 1729)] * 2


def test_scene_review_requires_intact_real_evidence(tmp_path):
    frame = tmp_path / "probe.png"
    frame.write_bytes(b"test evidence payload")
    report = {"qualified": True, "scene_review_approved": False, "environment_fingerprint": "env",
              "checks": {"scene_probes": {"passed": True}}, "evidence_sha256": {"probe.png": digest(frame)}}
    report_path = tmp_path / "qualification.json"
    write_json(report_path, report)
    approved = approve_scene_review(report_path)
    runner = LiberoRunner(tmp_path, qualification_path=report_path)
    runner.fingerprint = "env"
    runner._qualification_gate()
    assert approved["scene_review"]["evidence_hash"] == json_hash(report["evidence_sha256"])
    frame.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        approve_scene_review(report_path)
    fresh_runner = LiberoRunner(tmp_path, qualification_path=report_path)
    fresh_runner.fingerprint = "env"
    with pytest.raises(SimulationError, match="evidence changed"):
        fresh_runner._qualification_gate()


class ArrayTensor:
    def __init__(self, value):
        self.value = np.asarray(value)
    def __getitem__(self, index):
        return ArrayTensor(self.value[index])
    def cpu(self):
        return self
    def detach(self):
        return self
    def numpy(self):
        return self.value


class StubRecorder:
    def __init__(self, output_dir, fps, **kwargs):
        self.frames, self.actions = [], []
        self.encode_seconds = 0.0
    def observation(self, pixels, state, sim_state, simulation_time, success, **kwargs):
        self.frames.append({"success": success})
    def action(self, action, reward, terminated, truncated):
        self.actions.append(action)
    def close(self):
        pass


class ContractRunner(LiberoRunner):
    """Test only the rollout control flow using a deterministic host simulator."""
    def _load(self):
        self._loaded = True
        self.np = np
        self.torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda: None, reset_peak_memory_stats=lambda: None,
            max_memory_allocated=lambda: 0), inference_mode=contextlib.nullcontext)
        self.policy = SimpleNamespace(select_action=lambda batch: ArrayTensor(np.zeros((1, 7))))
        self.postprocessor = lambda action: action
        self.env_postprocessor = lambda transition: transition
        self.environment, self.task_identity, self.fingerprint = {}, {}, "test-only"
    def _reset(self, state_id, seed):
        self.count = 0
        self.settled = np.zeros(5)
        self.sim = SimpleNamespace(get_state=lambda: np.zeros(5), data=SimpleNamespace(time=0.0, qpos=np.zeros(2), qvel=np.zeros(2)),
            model=SimpleNamespace(njnt=2, nq=2, nv=2, opt=SimpleNamespace(timestep=.002),
                joint_id2name=lambda i: f"joint{i}", jnt_type=[3, 3], jnt_qposadr=[0, 1], jnt_dofadr=[0, 1]))
        self.raw = SimpleNamespace(check_success=lambda: self.count == getattr(self, "success_at", -1))
        self._env = SimpleNamespace(step=self.step)
        return {"pixels": {}}, np.zeros(5)
    def _apply_scene(self, change):
        self.scene_evidence = {}
        return {"pixels": {}}
    def _environment_observation(self, observation):
        return {"observation.state": ArrayTensor(np.zeros((1, 8)))}
    def _policy_observation(self, batch):
        return batch
    def step(self, action):
        self.count += 1
        success = self.raw.check_success()
        return {"pixels": {}}, 1000.0, self.count == getattr(self, "terminate_at", -1), False, {"is_success": success}


@pytest.mark.parametrize("success_at,terminate_at,expected,steps", [(-1, -1, "horizon_exhausted", 3),
    (2, -1, "success", 2), (-1, 1, "terminated_without_success", 1)])
def test_rollout_enforces_horizon_and_uses_success_predicate_not_reward(tmp_path, monkeypatch, success_at, terminate_at, expected, steps):
    monkeypatch.setattr("failureforge.simulation.libero.EpisodeRecorder", StubRecorder)
    runner = ContractRunner(tmp_path)
    runner.success_at, runner.terminate_at = success_at, terminate_at
    result = runner.run(REQUEST, tmp_path / "episode")
    assert result["outcome"] == expected
    assert result["steps"] == steps
    assert result["task_success"] == (expected == "success")
    assert result["metadata"]["frame_count"] == steps + 1
    physics = json.loads((tmp_path / "episode" / "environment.json").read_text())["physics"]
    assert physics["physics_timestep_seconds"] == .002
    assert physics["joints"][1]["qpos_start"] == 1


def test_cancellation_before_first_action_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr("failureforge.simulation.libero.EpisodeRecorder", StubRecorder)
    result = ContractRunner(tmp_path).run(REQUEST, tmp_path / "episode", lambda: True)
    assert result["outcome"] == "cancelled"
    assert result["steps"] == 0
    assert not result["task_success"]


@pytest.mark.gpu
@pytest.mark.skipif(os.environ.get("FAILUREFORGE_RUN_GPU_TESTS") != "1", reason="Explicit target-PC GPU opt-in required")
def test_real_episode_has_two_cameras_and_terminal_trace(tmp_path):
    """Short smoke only; full baseline qualification remains a separate gate."""
    runner = LiberoRunner(Path(os.environ["FAILUREFORGE_MODEL_PATH"]))
    try:
        result = runner.run({**REQUEST, "max_steps": 2}, tmp_path / "real")
        assert result["steps"] <= 2
        with np.load(tmp_path / "real" / "traces.npz", allow_pickle=False) as trace:
            assert trace["states"].shape == (result["steps"] + 1, 8)
            assert trace["actions"].shape == (result["steps"], 7)
            assert trace["qpos"].shape[0] == result["steps"] + 1
            assert trace["qvel"].shape[0] == result["steps"] + 1
            assert np.all(np.isfinite(trace["states"]))
        for camera in ("main.mp4", "wrist.mp4"):
            assert (tmp_path / "real" / camera).stat().st_size > 0
    finally:
        runner.close()


@pytest.mark.gpu
@pytest.mark.skipif(os.environ.get("FAILUREFORGE_RUN_GPU_TESTS") != "1", reason="Explicit target-PC GPU opt-in required")
def test_real_identity_camera_light_effects_and_reset_isolation(tmp_path):
    from failureforge.simulation.qualification import _scene_probes
    runner = LiberoRunner(Path(os.environ["FAILUREFORGE_MODEL_PATH"]))
    try:
        runner._load()
        report = _scene_probes(runner, tmp_path / "scene-probes")
        assert report["passed"], report["checks"]
        assert report["target_visibility_review"] == "pending"
    finally:
        runner.close()
