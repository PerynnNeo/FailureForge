#!/usr/bin/env python3
"""Explicit target-PC installer: download only pinned inference assets, no training data.

Does not import LIBERO (which can prompt on import), torch, or instantiate a model.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from failureforge.simulation.profile import POLICY_REPO, POLICY_REVISION, tree_hashes, verify_bootstrap, write_json


def nested_value(value, key):
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = nested_value(child, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = nested_value(child, key)
            if found is not None:
                return found
    return None


def bootstrap(root: Path) -> dict:
    from huggingface_hub import HfApi, snapshot_download
    import yaml

    root = root.resolve()
    model_path = root / "models" / "smolvla_libero"
    existing = model_path / "failureforge-bootstrap.json"
    if existing.exists():
        result = verify_bootstrap(model_path)
        print(f"Existing bootstrap verified: {existing}")
        return result
    package = importlib.util.find_spec("libero")
    if package is None or package.origin is None:
        raise RuntimeError("hf-libero is absent; run scripts/setup_robotics.sh in Linux first")
    libero_root = Path(package.origin).parent / "libero"
    config_dir = Path(os.environ.get("LIBERO_CONFIG_PATH", str(root / "environment" / "libero-config"))).resolve()
    paths = {"benchmark_root": libero_root, "assets": root / "data" / "libero-assets",
        "bddl_files": libero_root / "bddl_files", "init_states": libero_root / "init_files",
        "datasets": root / "data" / "datasets"}
    for key in ("bddl_files", "init_states"):
        if not paths[key].is_dir():
            raise RuntimeError(f"Installed package lacks {key}: {paths[key]}")
    desired = {k: str(v) for k, v in paths.items()}
    config_file = config_dir / "config.yaml"
    if config_file.exists():
        current = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        if current != desired:
            raise RuntimeError(f"Existing LIBERO config differs; preserved unchanged: {config_file}")
    for key in ("datasets", "assets"):
        paths[key].mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    if not config_file.exists():
        config_file.write_text(yaml.safe_dump(desired, sort_keys=True), encoding="utf-8")
    api = HfApi()
    asset_info = api.dataset_info("lerobot/libero-assets")
    snapshot_download("lerobot/libero-assets", repo_type="dataset", revision=asset_info.sha,
                      local_dir=str(paths["assets"]))
    snapshot_download(POLICY_REPO, revision=POLICY_REVISION, local_dir=str(model_path))
    for filename in ("config.json", "model.safetensors", "policy_preprocessor.json", "policy_postprocessor.json"):
        if not (model_path / filename).is_file():
            raise RuntimeError(f"Checkpoint snapshot lacks required file: {filename}")
    config = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
    processor = json.loads((model_path / "policy_preprocessor.json").read_text(encoding="utf-8"))
    tokenizer_repo = nested_value(processor, "tokenizer_name")
    vlm_repo = config.get("vlm_model_name", "HuggingFaceTB/SmolVLM2-500M-Video-Instruct")
    dependencies = {}
    for repo in sorted({vlm_repo, tokenizer_repo} - {None}):
        info = api.model_info(repo)
        if not info.sha:
            raise RuntimeError(f"Could not resolve dependency revision: {repo}")
        path = root / "models" / "dependencies" / repo.replace("/", "--") / info.sha
        snapshot_download(repo, revision=info.sha, local_dir=str(path))
        dependencies[repo] = {"repo_id": repo, "revision": info.sha, "path": str(path), "sha256": tree_hashes(path),
            "license": getattr(info.card_data, "license", None)}
    manifest = {"schema_version": "1.0", "policy": {"repo_id": POLICY_REPO, "revision": POLICY_REVISION,
            "path": str(model_path), "sha256": tree_hashes(model_path)},
        "dependencies": dependencies, "tokenizer_repo": tokenizer_repo, "libero_config_dir": str(config_dir),
        "assets": {"repo_id": "lerobot/libero-assets", "revision": asset_info.sha, "path": str(paths["assets"]),
            "sha256": tree_hashes(paths["assets"]), "license": getattr(asset_info.card_data, "license", None)},
        "offline_execution_verified": False}
    write_json(existing, manifest)
    verify_bootstrap(model_path)
    print(f"Prepared pinned snapshots and verified file hashes: {existing}")
    print("GPU rendering, policy competence, and offline execution remain untested. Run qualification on the target PC.")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    bootstrap(args.root)
