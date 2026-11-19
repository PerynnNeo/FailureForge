"""Version and content identity for the supported, source-reviewed runtime."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path

POLICY_REPO = "lerobot/smolvla_libero"
POLICY_REVISION = "a24f1f380461b665158d52acd140152c79e8b36d"
TASK_NAME = "pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate"
TASK_SUITE = "libero_spatial"
TASK_ID = 2
ADAPTER_VERSION = "libero-0.6.1-v1"
VERSIONS = {"lerobot": "0.6.1", "hf-libero": "0.1.4", "robosuite": "1.4.0", "mujoco": "3.8.1",
            "torch": "2.11.0+cu128", "torchvision": "0.26.0+cu128"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def tree_hashes(path: Path) -> dict[str, str]:
    return {p.relative_to(path).as_posix(): digest(p) for p in sorted(path.rglob("*"))
            if p.is_file() and ".cache" not in p.relative_to(path).parts and ".git" not in p.relative_to(path).parts}


def doctor(model_path: Path | None = None, *, cuda: bool = False) -> dict:
    """Read package metadata only by default. --cuda explicitly performs a real GPU op."""
    versions = {}
    for name in (*VERSIONS, "numpy", "scipy", "pydantic", "av", "pillow", "transformers", "safetensors"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    failures = [f"{name}: expected {expected}, installed {versions[name]}"
                for name, expected in VERSIONS.items() if versions[name] != expected]
    if platform.system() != "Linux":
        failures.append("Robotics execution requires Linux; laptop application development remains supported.")
    if sys.version_info[:2] != (3, 12):
        failures.append("Reference robotics runtime requires Python 3.12.")
    result = {"schema_version": "1.0", "adapter_version": ADAPTER_VERSION, "platform": platform.platform(),
              "cpu": platform.processor() or platform.machine(),
              "python": sys.version, "packages": versions, "sqlite": sqlite3.sqlite_version,
              "profile_compatible": not failures, "failures": failures, "cuda_test": "not_run",
              "renderer_test": "not_run", "policy_episode_test": "not_run", "qualified": False}
    if model_path is not None:
        result["model_present"] = all((Path(model_path) / p).is_file() for p in (
            "config.json", "model.safetensors", "policy_preprocessor.json", "policy_postprocessor.json", "failureforge-bootstrap.json"))
    if cuda:
        try:
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA is unavailable")
            tensor = torch.ones((16, 16), device="cuda")
            measured = float((tensor @ tensor).sum().item())
            torch.cuda.synchronize()
            if measured != 4096.0:
                raise RuntimeError("CUDA matrix computation returned an unexpected result")
            result.update(cuda_test="passed", gpu=torch.cuda.get_device_name(0), cuda=torch.version.cuda,
                          gpu_memory_bytes=torch.cuda.get_device_properties(0).total_memory,
                          gpu_compute_capability=list(torch.cuda.get_device_capability(0)),
                          cudnn_version=torch.backends.cudnn.version())
            try:
                result["nvidia_driver"] = subprocess.check_output(["nvidia-smi", "--query-gpu=driver_version",
                    "--format=csv,noheader"], text=True, timeout=10).strip().splitlines()[0]
            except (OSError, subprocess.SubprocessError, IndexError):
                result["nvidia_driver"] = "unavailable"
        except Exception as exc:
            result.update(cuda_test="failed", cuda_error=f"{type(exc).__name__}: {exc}")
    return result


def source_identity(module_path: Path) -> dict:
    """Require the frozen checkout rather than accepting an unrelated editable install."""
    source_root = next((p for p in module_path.parents if (p / "uv.lock").is_file() and (p / ".git").exists()), None)
    if source_root is None:
        raise RuntimeError("LeRobot must be installed from vendor/lerobot's frozen v0.6.1 checkout")
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(source_root), *args], text=True, timeout=15).strip()
    head = git("rev-parse", "HEAD")
    tag = git("rev-parse", "v0.6.1^{commit}")
    if head != tag or not head.startswith("7e241bd"):
        raise RuntimeError(f"Unexpected LeRobot source revision: {head}")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("LeRobot checkout has tracked modifications; restore the frozen source profile")
    return {"commit": head, "uv_lock_sha256": digest(source_root / "uv.lock"),
            "libero_adapter_sha256": digest(module_path)}


def verify_bootstrap(model_path: Path) -> dict:
    manifest = json.loads((model_path / "failureforge-bootstrap.json").read_text(encoding="utf-8"))
    if manifest.get("policy", {}).get("revision") != POLICY_REVISION or manifest["policy"].get("repo_id") != POLICY_REPO:
        raise RuntimeError("Bootstrap does not identify the supported checkpoint revision")
    for section in [manifest["policy"], *manifest["dependencies"].values(), manifest["assets"]]:
        root = model_path if section is manifest["policy"] else Path(section["path"])
        if not section.get("sha256"):
            raise RuntimeError("Bootstrap section has no content hashes")
        for relative, expected in section["sha256"].items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file() or digest(path) != expected:
                raise RuntimeError(f"Bootstrap file missing or changed: {relative}")
    return manifest
