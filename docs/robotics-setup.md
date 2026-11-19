# FailureForge on the execution PC

The target PC uses Ubuntu 24.04 under WSL2. The frozen runtime has run the bowl-to-plate policy with CUDA 12.8 on an RTX 5090. See [build status](build-status.md) for the observed outcomes and evidence. The lightweight app can also run independently on a development machine.

## Prepare Linux and the frozen runtime

Keep the checkout, SQLite database, and artifacts on the Linux filesystem, for example `~/FailureForge`. Use the Windows NVIDIA driver for WSL; do not install a Linux display driver inside WSL. Install system dependencies and `uv` using their official instructions:

```bash
sudo apt update
sudo apt install -y git build-essential cmake ffmpeg libgl1 libegl1 libglfw3 libosmesa6
bash scripts/setup_robotics.sh
```

The setup script clones LeRobot v0.6.1, verifies its tag and source commit prefix `7e241bd`, resolves the full commit, and synchronizes the release's **frozen** lock with the evaluation, LIBERO, and SmolVLA extras. It records the full commit, lock checksum, and uv version in `environment/`. It rejects a modified or different existing checkout. It does not upgrade PyTorch independently.

The tested package tuple is Python 3.12, LeRobot 0.6.1, torch 2.11.0+cu128, torchvision 0.26.0+cu128, hf-libero 0.1.4, robosuite 1.4.0, and MuJoCo 3.8.1. Bootstrap links the installed LIBERO arena asset path to its verified downloaded snapshot, since this release reads some scene files directly from the package location.

The bootstrap downloads the complete `lerobot/smolvla_libero` revision `a24f1f380461b665158d52acd140152c79e8b36d`, including checkpoint processors and normalization safetensors. It resolves the asset dataset and the checkpoint's VLM/tokenizer references to exact revisions and hashes their files. It downloads inference dependencies, not the training dataset. It writes project-local LIBERO configuration before importing the simulator and preserves any differing existing config. Hugging Face access and sufficient disk space are required only for this explicit preparation step.

`models/smolvla_libero/failureforge-bootstrap.json` records all content identities and absolute dependency paths. To relocate the installation, prepare it at the destination and requalify. Loading uses explicit local dependency paths with Hugging Face/Transformers offline mode enabled, preventing an unnoticed network fetch during an episode. For an independent offline acceptance check, disconnect the execution PC's network and rerun qualification or a qualified case.

The lightweight app and frozen robotics runtime remain separate. Do not install the app's complete pinned web dependencies into the robotics environment. Setup checks that the CLI and shared schemas import against the frozen NumPy/SciPy/Pydantic versions and records them in `environment/app-contract-smoke.json`; actual command execution is still validated on the PC. Expose the source to the frozen interpreter:

```bash
export PYTHONPATH="$PWD/src"
export LIBERO_CONFIG_PATH="$PWD/environment/libero-config"
export MUJOCO_GL=egl
vendor/lerobot/.venv/bin/python -m failureforge doctor --robotics
```

`doctor` reads distribution metadata and reports missing/incompatible packages without importing CUDA or the simulator. To explicitly check an actual CUDA operation:

```bash
vendor/lerobot/.venv/bin/python -c 'import json; from failureforge.simulation import doctor; print(json.dumps(doctor(cuda=True), indent=2))'
```

## Execute qualification and inspect the evidence

The following executes twelve complete reference episodes plus static scene probes. It reserves qualification states 12..21, search states 0 and 1, and leaves confirmation states 2..11 untouched. Qualification seeds are `1729 + state_id`. Campaigns additionally execute fresh matched reference checks under their own recorded policy seed schedule.

```bash
timeout --signal=TERM --kill-after=10s 2h \
  vendor/lerobot/.venv/bin/python -m failureforge --data-dir data qualify \
  --model-path models/smolvla_libero --renderer egl
```

The external timeout is intentional: native rendering can hang, and a pinned LIBERO reset retry loop can swallow Python exceptions. Live campaign execution has a parent-process episode watchdog; qualification is an explicit host diagnostic and uses this process-level timeout. An interrupted qualification remains incomplete. Preserve its directory, choose a new data directory for a new attempt, and do not erase unsuccessful reference episodes from the reported allocation.

The report at `data/qualification/qualification.json` requires at least eight successes in the ten designated qualification episodes, success on both designated search reference states, no infrastructure failures, and passing scene checks. It asserts the installed task name at suite `libero_spatial`, task ordering 0, ID 2. Task BDDL, benchmark state file, source code, model files, dependency files, driver, GPU, dtype, TF32 settings and renderer contribute to the recorded execution identity.

Open `data/qualification/scene-probes/scene-contact-sheet.png` and each full-size main/wrist image. The probe grid includes identity, both parameter-axis extremes, and all four domain corners. Check that the bowl and plate are visible, the orientation is correct, and lighting and occlusion remain meaningful. Automated checks verify finite camera tensors, actual policy-input changes, unchanged initial mechanics, the unchanged wrist pose, and changed-to-reference reset isolation. Pixel checks cannot decide whether the target is visible enough for the intended study.

After **you have inspected those generated images**, record the review:

```bash
vendor/lerobot/.venv/bin/python -m failureforge --data-dir data approve-scene-review
```

This records an explicit operator attestation tied to hashes of the actual evidence. It does not substitute for the inspection. The implementation does not preapprove this step. A live worker rejects missing qualification, pending scene review, changed evidence, or a changed runtime fingerprint.

After review, **New campaign** lets you inspect both recorded policy-camera views for completed reference episodes before submitting work. Playback remains available while the worker is offline. The local API lists these states at `GET /api/qualification/references`. Each camera link verifies its MP4 against the reviewed manifest before serving the recording. In-progress qualification directories and operator diagnostics stay private.

Start the sequential robot worker:

```bash
vendor/lerobot/.venv/bin/python -m failureforge --data-dir data worker \
  --backend libero --model-path models/smolvla_libero --renderer egl --episode-timeout 600
```

Run the API separately using the lightweight app environment and the same local `data` directory. Start conservatively on loopback; use the documented authenticated transport before configuring access from the laptop.

In a second terminal at the repository root (with Python 3.12 and Node 22 or later available):

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r environment-app-lock.txt
.venv/bin/python -m pip install -e . --no-deps
npm ci --prefix apps/web
npm run build --prefix apps/web
.venv/bin/python -m failureforge --data-dir data serve
```

Open `http://127.0.0.1:8000` on the PC, or use the SSH forwarding instructions in the README from the laptop. Both processes must point to this same checkout's local `data` directory.

EGL is the initial renderer. GLFW with WSLg or OSMesa may be tried as explicit alternative profiles if EGL fails. Robosuite 1.4.0 may override backend environment configuration in some installations; the adapter checks the effective backend and rejects a mismatch. A different working renderer requires fresh qualification. Native Linux is the fallback when the complete WSL inference/render pipeline is unstable.

## Episode evidence and reproducibility

Each attempt has its own directory. The runner writes `spec.json`, `outcome.json`, `environment.json`, `task_identity.json`, `scene_change.json`, `initial_state.npz`, `traces.npz`, `frames.json`, `main.mp4`, and `wrist.mp4`. The artifact publisher adds checksums and publishes only complete successful writes. Exceptions produce `error.json`; they remain infrastructure evidence rather than counted robot failures.

`initial_state.npz` stores the trusted benchmark state separately from the settled first-action state. Fresh runs restore the chosen benchmark index, perform the pinned ten settling steps once, then modify and refresh the scene using the **current settled state**. The policy action queue and processor state reset once per episode. The policy retains its 50-action chunk and declared 20 Hz control rate.

Video contains the actual two policy camera views with the same 180-degree orientation correction as the environment processor, encoded at 20 FPS. Frame/state 0 is the initial observation; frame/state `i+1` follows action `i`; the terminal observation is retained. `traces.npz` contains numeric arrays only and must be opened with `allow_pickle=False`. State, simulator `qpos`/`qvel`, and success arrays have `steps + 1` rows; action, reward, terminated and truncated arrays have `steps` rows. `environment.json` and `frames.json` record the actual physics timestep and every named joint's half-open qpos/qvel index intervals and coordinate convention. The runner enforces the 280-step horizon independently of the wrapper and records the task's own success predicate after every step.

Camera displacement is in `agentview`'s parent frame. Lighting multiplies baseline ambient, diffuse and specular arrays and clips them to `[0,1]`. Each hard reset refreshes those baseline arrays; repeated scene applications do not accumulate changes. Scene arrays and parent-body identity are saved in `scene_change.json`.

Model-loading, reset, inference/processing, simulation/rendering, and video-encoding time are recorded separately. GPU timing is synchronized. Inference time includes action-queue calls, not an assertion that a new neural-network chunk is generated at every control step. Cross-device byte-identical trajectories are not promised; compare recorded identities, outcomes and explicit numerical tolerances.

Optional target-PC smoke test:

```bash
FAILUREFORGE_RUN_GPU_TESTS=1 FAILUREFORGE_MODEL_PATH="$PWD/models/smolvla_libero" \
  vendor/lerobot/.venv/bin/python -m pytest tests/test_simulation_contract.py -m gpu
```

The upstream test extra may be needed to provide pytest. The GPU tests execute a short episode plus the scene identity/effect/reset checks. The twelve-episode qualification gate and the subsequent campaign each have separate allocations. [Execution PC results](execution-host-results.md) records the actual runs, evidence and limitations.

Source references: [pinned LIBERO adapter](https://raw.githubusercontent.com/huggingface/lerobot/v0.6.1/src/lerobot/envs/libero.py), [environment processor](https://raw.githubusercontent.com/huggingface/lerobot/v0.6.1/src/lerobot/processor/env_processor.py), [policy processors](https://raw.githubusercontent.com/huggingface/lerobot/v0.6.1/src/lerobot/policies/factory.py), [SmolVLA model](https://raw.githubusercontent.com/huggingface/lerobot/v0.6.1/src/lerobot/policies/smolvla/modeling_smolvla.py), [reference evaluator](https://raw.githubusercontent.com/huggingface/lerobot/v0.6.1/src/lerobot/scripts/lerobot_eval.py), [NVIDIA WSL instructions](https://docs.nvidia.com/cuda/wsl-user-guide/index.html).
