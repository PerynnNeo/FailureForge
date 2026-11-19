import hashlib
import io
import json
import zipfile

import numpy as np
import pytest

from failureforge.artifacts import ArtifactError, ArtifactStore, inspect_bundle, safe_relative
from failureforge.contracts import CampaignSpec
from failureforge.simulation.synthetic import SyntheticRunner


@pytest.mark.parametrize("name", ["../file", "/file", "C:/file", "a\\b", "a/../b", "a//b", "a/./b"])
def test_unsafe_paths_rejected(name):
    with pytest.raises(ArtifactError):
        safe_relative(name)


def test_attempt_directory_and_checksum_are_immutable(tmp_path):
    artifacts = ArtifactStore(tmp_path)
    directory = artifacts.begin_episode("episode_test", "token")
    result = SyntheticRunner().run({"state_id": 0, "seed": 1, "scene_change": {"main_camera_dx_m": 0, "light_scale": 1}, "max_steps": 280, "control_hz": 20}, directory)
    manifest = artifacts.publish_episode("episode_test", "token", directory, result)
    artifacts.verify_episode(manifest)
    item = dict(manifest["files"][0], relative_dir=manifest["relative_dir"])
    path = artifacts.resolve(item)
    path.write_bytes(b"corrupted")
    with pytest.raises(ArtifactError, match="checksum"):
        artifacts.resolve(item)


def test_publication_retries_transient_windows_lock_without_partial_copy(tmp_path, monkeypatch):
    from pathlib import Path
    artifacts = ArtifactStore(tmp_path)
    directory = artifacts.begin_episode("episode_locked", "token")
    result = SyntheticRunner().run({"state_id": 0, "seed": 1, "scene_change": {"main_camera_dx_m": 0, "light_scale": 1}, "max_steps": 280, "control_hz": 20}, directory)
    rename = Path.rename
    attempts = []

    def temporarily_locked(path, destination):
        attempts.append(destination)
        assert not destination.exists()
        if len(attempts) < 3:
            error = PermissionError("temporary scanner lock")
            error.winerror = 32
            raise error
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", temporarily_locked)
    manifest = artifacts.publish_episode("episode_locked", "token", directory, result)
    assert len(attempts) == 3
    assert not directory.exists()
    artifacts.verify_episode(manifest)


def test_zip_traversal_rejected_without_extracting(tmp_path):
    bundle = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("../outside.json", "{}")
    with pytest.raises(ArtifactError, match="Unsafe"):
        inspect_bundle(bundle)
    assert not (tmp_path.parent / "outside.json").exists()


def test_duplicate_zip_members_rejected(tmp_path):
    bundle = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("spec.json", "{}")
        with pytest.warns(UserWarning):
            archive.writestr("spec.json", "{}")
    with pytest.raises(ArtifactError, match="duplicate"):
        inspect_bundle(bundle)


@pytest.fixture
def portable_bundle(tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    request = {"backend": "synthetic", "state_id": 0, "seed": 1729,
               "scene_change": {"main_camera_dx_m": 0, "light_scale": 1}, "max_steps": 280, "control_hz": 20}
    directory = artifacts.begin_episode("episode_test", "attempt")
    result = SyntheticRunner().run(request, directory)
    manifest = artifacts.publish_episode("episode_test", "attempt", directory, result)
    episode = {"id": "episode_test", "status": "completed", "request": {**request, "_retry": False},
               "result": result, "outcome": result["outcome"], "artifact_manifest": manifest,
               "phase": "baseline", "state_id": 0, "condition": "reference"}
    case = {"id": "case_test", "backend": "synthetic", "evidence_kind": "synthetic_diagnostic", "episodes": [episode]}
    campaign = {"backend": "synthetic", "spec": CampaignSpec(backend="synthetic").model_dump(mode="json"), "budget": {}}
    return artifacts.export_case(case, campaign)


def _json_bytes(value):
    return json.dumps(value, allow_nan=False).encode("utf-8")


def _edit_json(members, name, change):
    value = json.loads(members[name])
    change(value)
    members[name] = _json_bytes(value)


def _forge_bundle(source, target, change, *, reseal_nested=True):
    """Recompute both checksum layers: tests must exercise semantics, not stale hashes."""
    with zipfile.ZipFile(source) as archive:
        members = {item.filename: archive.read(item) for item in archive.infolist()}
    change(members)
    if reseal_nested:
        for name in list(members):
            if name.startswith("episodes/") and name.endswith("/manifest.json"):
                manifest = json.loads(members[name])
                prefix = name.removesuffix("manifest.json")
                for record in manifest["files"]:
                    content = members[prefix + record["path"]]
                    record.update(size=len(content), sha256=hashlib.sha256(content).hexdigest())
                members[name] = _json_bytes(manifest)
    manifest = json.loads(members["manifest.json"])
    manifest["files"] = [{"path": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                         for name, content in sorted(members.items()) if name not in {"manifest.json", "checksums.sha256"}]
    members["manifest.json"] = _json_bytes(manifest)
    members["checksums.sha256"] = "".join(
        f"{hashlib.sha256(content).hexdigest()}  {name}\n"
        for name, content in sorted(members.items()) if name != "checksums.sha256").encode()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return target


EPISODE = "episodes/episode_test/"


def test_valid_synthetic_export_verifies_nested_payloads_without_extraction(portable_bundle, tmp_path):
    before = set(tmp_path.rglob("*"))
    verified = inspect_bundle(portable_bundle)
    assert verified["valid"] and verified["backend"] == "synthetic"
    assert verified["manifest"]["episode_manifests"] == [EPISODE + "manifest.json"]
    assert before == set(tmp_path.rglob("*"))


@pytest.mark.parametrize("name", ["manifest.json", "spec.json", "case.json", EPISODE + "manifest.json",
                                  EPISODE + "spec.json", EPISODE + "outcome.json", EPISODE + "environment.json",
                                  EPISODE + "scene_change.json", EPISODE + "task_identity.json"])
def test_forged_backend_mismatch_rejected(portable_bundle, tmp_path, name):
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip",
                           lambda members: _edit_json(members, name, lambda value: value.update(backend="libero")))
    with pytest.raises(ArtifactError, match="[Bb]ackend|[Ee]vidence"):
        inspect_bundle(forged)


@pytest.mark.parametrize("name", ["manifest.json", "spec.json", "case.json", EPISODE + "manifest.json",
                                  EPISODE + "outcome.json", EPISODE + "environment.json", EPISODE + "frames.json"])
def test_forged_schema_mismatch_rejected(portable_bundle, tmp_path, name):
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip",
                           lambda members: _edit_json(members, name, lambda value: value.update(schema_version="999")))
    with pytest.raises(ArtifactError, match="schema"):
        inspect_bundle(forged)


def test_missing_required_role_rejected_after_resealing(portable_bundle, tmp_path):
    def corrupt(members):
        _edit_json(members, EPISODE + "manifest.json", lambda value: value["files"][0].pop("role"))
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip", corrupt)
    with pytest.raises(ArtifactError, match="role"):
        inspect_bundle(forged)


def test_missing_required_file_rejected_after_resealing(portable_bundle, tmp_path):
    def corrupt(members):
        del members[EPISODE + "initial_state.npz"]
        _edit_json(members, EPISODE + "manifest.json",
                   lambda value: value.update(files=[r for r in value["files"] if r["path"] != "initial_state.npz"]))
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip", corrupt)
    with pytest.raises(ArtifactError, match="required files"):
        inspect_bundle(forged)


def test_robot_bundle_requires_both_camera_recordings(portable_bundle, tmp_path):
    def relabel(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "backend":
                    value[key] = "libero"
                elif key == "evidence_kind":
                    value[key] = "robot_simulation"
                else:
                    relabel(item)
        elif isinstance(value, list):
            for item in value:
                relabel(item)
    def corrupt(members):
        for name in members:
            if name.endswith(".json"):
                _edit_json(members, name, relabel)
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip", corrupt)
    with pytest.raises(ArtifactError, match="main.mp4, wrist.mp4"):
        inspect_bundle(forged)


@pytest.mark.parametrize("change", ["missing_manifest", "extra_completed", "uncompleted_payload", "duplicate_episode"])
def test_episode_membership_exactly_matches_completed_case_entries(portable_bundle, tmp_path, change):
    def corrupt(members):
        if change == "missing_manifest":
            _edit_json(members, "manifest.json", lambda value: value.update(episode_manifests=[]))
        elif change == "extra_completed":
            _edit_json(members, "case.json", lambda value: value["episodes"].append({**value["episodes"][0], "id": "episode_missing"}))
        elif change == "uncompleted_payload":
            _edit_json(members, "case.json", lambda value: value["episodes"][0].update(status="error"))
        else:
            _edit_json(members, "case.json", lambda value: value["episodes"].append(value["episodes"][0]))
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip", corrupt)
    with pytest.raises(ArtifactError, match="[Ee]pisode|completed"):
        inspect_bundle(forged)


def test_nested_manifest_checksum_must_match_outer_record(portable_bundle, tmp_path):
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip", lambda members: _edit_json(
        members, EPISODE + "manifest.json", lambda value: value["files"][0].update(sha256="0" * 64)), reseal_nested=False)
    with pytest.raises(ArtifactError, match="Nested episode checksum"):
        inspect_bundle(forged)


@pytest.mark.parametrize("name,change", [
    (EPISODE + "spec.json", {"seed": 77}),
    (EPISODE + "outcome.json", {"steps": 10}),
    (EPISODE + "task_identity.json", {"state_id": 5}),
    (EPISODE + "scene_change.json", {"scene_change": {"main_camera_dx_m": 0.04, "light_scale": 1}}),
])
def test_payload_disagreements_rejected(portable_bundle, tmp_path, name, change):
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip",
                           lambda members: _edit_json(members, name, lambda value: value.update(change)))
    with pytest.raises(ArtifactError, match="differs"):
        inspect_bundle(forged)


def _npz_member(npy):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload.npy", npy)
    return stream.getvalue()


def test_object_array_rejected_in_resealed_bundle(portable_bundle, tmp_path):
    stream = io.BytesIO()
    np.save(stream, np.array([{"untrusted": True}], dtype=object), allow_pickle=True)
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip",
                           lambda members: members.update({EPISODE + "traces.npz": _npz_member(stream.getvalue())}))
    with pytest.raises(ArtifactError, match="Object arrays"):
        inspect_bundle(forged)


def test_huge_npy_declared_shape_rejected_before_numpy_load(portable_bundle, tmp_path, monkeypatch):
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(stream, {"descr": "<f8", "fortran_order": False, "shape": (2**60,)})
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip",
                           lambda members: members.update({EPISODE + "initial_state.npz": _npz_member(stream.getvalue())}))
    # The malicious array is first alphabetically. Loading must never be attempted.
    monkeypatch.setattr(np, "load", lambda *args, **kwargs: pytest.fail("NPY allocation attempted before preflight"))
    with pytest.raises(ArtifactError, match="allocation limit"):
        inspect_bundle(forged)


def test_npy_declared_shape_must_match_actual_bytes(portable_bundle, tmp_path):
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(stream, {"descr": "<f8", "fortran_order": False, "shape": (10,)})
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip",
                           lambda members: members.update({EPISODE + "traces.npz": _npz_member(stream.getvalue())}))
    with pytest.raises(ArtifactError, match="payload size"):
        inspect_bundle(forged)


def test_inner_npz_expansion_limit_checked_before_loading(portable_bundle, tmp_path, monkeypatch):
    stream = io.BytesIO()
    np.save(stream, np.zeros(2048, dtype=np.uint8), allow_pickle=False)
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip",
                           lambda members: members.update({EPISODE + "initial_state.npz": _npz_member(stream.getvalue())}))
    monkeypatch.setattr("failureforge.artifacts.MAX_NUMPY_BYTES", 1024)
    monkeypatch.setattr(np, "load", lambda *args, **kwargs: pytest.fail("NPZ allocation attempted before expansion check"))
    with pytest.raises(ArtifactError, match="expansion"):
        inspect_bundle(forged)


@pytest.mark.parametrize("content", [b"not a zip", b"PK\x03\x04"])
def test_malformed_bundle_always_raises_artifact_error(tmp_path, content):
    bundle = tmp_path / "bad.zip"
    bundle.write_bytes(content)
    with pytest.raises(ArtifactError):
        inspect_bundle(bundle)


@pytest.mark.parametrize("name,content", [("case.json", b"[]"),
                                           (EPISODE + "outcome.json", b'{"steps":1,"steps":2}')])
def test_malformed_json_always_raises_artifact_error(portable_bundle, tmp_path, name, content):
    change = lambda members: members.update({name: content})
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip", change)
    with pytest.raises(ArtifactError):
        inspect_bundle(forged)


def test_malformed_manifest_json_raises_artifact_error(tmp_path):
    bundle = tmp_path / "malformed.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        for name, content in {"manifest.json": b"{", "case.json": b"{}", "spec.json": b"{}", "checksums.sha256": b""}.items():
            archive.writestr(name, content)
    with pytest.raises(ArtifactError, match="Malformed"):
        inspect_bundle(bundle)


def test_malformed_manifest_list_raises_artifact_error(portable_bundle, tmp_path):
    forged = _forge_bundle(portable_bundle, tmp_path / "forged.zip", lambda members: _edit_json(
        members, "manifest.json", lambda value: value.update(episode_manifests=23)))
    with pytest.raises(ArtifactError, match="manifest list"):
        inspect_bundle(forged)
