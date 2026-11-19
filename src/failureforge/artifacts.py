"""Immutable episode artifacts and portable, verifiable case bundles."""
from __future__ import annotations

import ast
import hashlib
import html
import io
import json
import lzma
import math
import mimetypes
import os
import re
import shutil
import stat
import struct
import tempfile
import time
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from .contracts import CampaignSpec, SCHEMA_VERSION, VALID_OUTCOMES, canonical_json, utc_now

ROLES = {"main.mp4": "main_video", "wrist.mp4": "wrist_video", "traces.npz": "trace",
         "frames.json": "frames", "initial_state.npz": "initial_state", "outcome.json": "outcome",
         "environment.json": "environment", "scene_change.json": "scene_change", "task_identity.json": "task_identity",
         "spec.json": "spec", "diagnostic.svg": "diagnostic"}
REQUIRED = {"spec.json", "outcome.json", "environment.json", "initial_state.npz", "traces.npz", "frames.json", "scene_change.json", "task_identity.json"}
SAFE_SUFFIXES = {".json", ".npz", ".mp4", ".md", ".html", ".txt", ".sha256", ".svg"}
MAX_NUMPY_BYTES = 256 * 1024**2
MAX_NPY_HEADER_BYTES = 64 * 1024
MAX_JSON_BYTES = 16 * 1024**2


class ArtifactError(ValueError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value):
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def safe_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise ArtifactError("Unsafe artifact path")
    path = PurePosixPath(value)
    if not value or any(ord(c) < 32 for c in value) or "\\" in value or ":" in value or path.is_absolute() or any(p in ("..", ".", "") for p in value.split("/")):
        raise ArtifactError("Unsafe artifact path")
    return path


def _safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value):
        raise ArtifactError("Invalid artifact identity")
    return value


def _validate_numpy(source):
    """Bound the inner ZIP and NPY allocations before calling NumPy; never unpickle."""
    import numpy as np
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 512 or sum(x.file_size for x in entries) > MAX_NUMPY_BYTES:
                raise ArtifactError("Numerical archive exceeds expansion or array-count limit")
            if len({x.filename for x in entries}) != len(entries):
                raise ArtifactError("Numerical archive contains duplicate arrays")
            for entry in entries:
                relative = safe_relative(entry.filename)
                if (len(relative.parts) != 1 or relative.suffix != ".npy" or entry.is_dir()
                        or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1):
                    raise ArtifactError("Unexpected numerical archive content")
                with archive.open(entry) as stream:
                    prefix = stream.read(8)
                    if len(prefix) != 8 or prefix[:6] != b"\x93NUMPY" or prefix[6:] not in (b"\x01\x00", b"\x02\x00", b"\x03\x00"):
                        raise ArtifactError("Invalid NPY format")
                    length_bytes = 2 if prefix[6] == 1 else 4
                    length_data = stream.read(length_bytes)
                    if len(length_data) != length_bytes:
                        raise ArtifactError("Truncated NPY header")
                    header_size = int.from_bytes(length_data, "little")
                    if header_size > MAX_NPY_HEADER_BYTES:
                        raise ArtifactError("NPY header exceeds limit")
                    header_bytes = stream.read(header_size)
                    if len(header_bytes) != header_size:
                        raise ArtifactError("Truncated NPY header")
                    header = ast.literal_eval(header_bytes.decode("utf-8" if prefix[6] == 3 else "latin1"))
                    if not isinstance(header, dict) or set(header) != {"descr", "fortran_order", "shape"}:
                        raise ArtifactError("Malformed NPY header")
                    shape = header["shape"]
                    if (not isinstance(shape, tuple) or len(shape) > 32
                            or any(type(d) is not int or d < 0 for d in shape)
                            or type(header["fortran_order"]) is not bool):
                        raise ArtifactError("Invalid NPY shape or layout")
                    dtype = np.dtype(header["descr"])
                    if dtype.hasobject:
                        raise ArtifactError("Object arrays are not permitted")
                    if dtype.kind not in "biufc" or dtype.itemsize <= 0:
                        raise ArtifactError("Only numeric and boolean arrays are permitted")
                    # This uses arbitrary-precision integer arithmetic, before ndarray allocation.
                    byte_count = math.prod(shape) * dtype.itemsize
                    if byte_count > MAX_NUMPY_BYTES or any(d > MAX_NUMPY_BYTES for d in shape):
                        raise ArtifactError("NPY declared shape exceeds allocation limit")
                    if 8 + length_bytes + header_size + byte_count != entry.file_size:
                        raise ArtifactError("NPY declared shape does not match payload size")
        if hasattr(source, "seek"):
            source.seek(0)
        with np.load(source, allow_pickle=False, max_header_size=MAX_NPY_HEADER_BYTES) as arrays:
            for name in arrays.files:
                value = arrays[name]
                if not np.all(np.isfinite(value)):
                    raise ArtifactError(f"Non-finite trace values: {name}")
    except ArtifactError:
        raise
    except (OSError, ValueError, TypeError, KeyError, EOFError, OverflowError, SyntaxError,
            RecursionError, zipfile.BadZipFile, RuntimeError, NotImplementedError,
            struct.error, zlib.error, lzma.LZMAError) as exc:
        raise ArtifactError(f"Malformed numerical archive: {exc}") from exc


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "staging").mkdir(exist_ok=True)
        (self.root / "episodes").mkdir(exist_ok=True)
        (self.root / "exports").mkdir(exist_ok=True)

    def begin_episode(self, episode_id, token) -> Path:
        directory = self.root / "staging" / f"{_safe_id(episode_id)}_{_safe_id(token)}"
        directory.mkdir(exist_ok=False)
        return directory

    def publish_episode(self, episode_id, token, path, result) -> dict:
        path = Path(path).resolve()
        expected = self.root / "staging" / f"{_safe_id(episode_id)}_{_safe_id(token)}"
        if path != expected or path.is_symlink():
            raise ArtifactError("Episode staging directory does not match its attempt")
        names = {p.name for p in path.iterdir()}
        required = REQUIRED | ({"main.mp4", "wrist.mp4"} if result.get("backend") == "libero" else set())
        if missing := required - names:
            raise ArtifactError(f"Episode lacks required files: {', '.join(sorted(missing))}")
        files = []
        for payload in sorted(path.iterdir()):
            if payload.is_symlink() or not payload.is_file() or payload.suffix not in SAFE_SUFFIXES:
                raise ArtifactError("Unexpected episode payload")
            if payload.name in ("manifest.json", "checksums.sha256"):
                raise ArtifactError("Runner must not supply publication metadata")
            if payload.suffix == ".npz":
                _validate_numpy(payload)
            if payload.suffix == ".json":
                canonical_json(json.loads(payload.read_text(encoding="utf-8")))
            artifact_id = "artifact_" + hashlib.sha256(f"{episode_id}/{token}/{payload.name}".encode()).hexdigest()[:32]
            files.append({"id": artifact_id, "path": payload.name, "role": ROLES.get(payload.name, payload.stem),
                          "sha256": digest(payload), "size": payload.stat().st_size,
                          "media_type": mimetypes.guess_type(payload.name)[0] or "application/octet-stream"})
        relative_dir = f"episodes/{episode_id}_{token}"
        manifest = {"schema_version": SCHEMA_VERSION, "episode_id": episode_id, "lease_token": token,
                    "backend": result.get("backend"), "evidence_kind": "robot_simulation" if result.get("backend") == "libero" else "synthetic_diagnostic",
                    "created_at": utc_now(), "relative_dir": relative_dir, "files": files}
        # Manifest is written last; directory remains hidden until DB-fenced finalization.
        write_json(path / "manifest.json", manifest)
        for payload in path.iterdir():
            with payload.open("rb+") as stream:
                os.fsync(stream.fileno())
        destination = self.root / relative_dir
        if destination.exists():
            raise ArtifactError("Immutable attempt directory already exists")
        # Windows scanners can briefly hold a directory after its payloads close.
        # Retry the same atomic rename; never fall back to a partially visible copy.
        for delay in (0.05, 0.1, 0.2, None):
            try:
                path.rename(destination)
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in (5, 32, 33) or delay is None:
                    raise
                time.sleep(delay)
        return manifest

    def resolve(self, artifact: dict, verify=True) -> Path:
        directory = safe_relative(artifact["relative_dir"])
        relative = safe_relative(artifact["path"])
        path = self.root.joinpath(*directory.parts, *relative.parts)
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root) or path.is_symlink() or not resolved.is_file():
            raise ArtifactError("Artifact is missing or outside the configured root")
        if verify and (resolved.stat().st_size != artifact["size"] or digest(resolved) != artifact["sha256"]):
            raise ArtifactError("Artifact checksum mismatch")
        return resolved

    def verify_episode(self, manifest):
        for artifact in manifest["files"]:
            self.resolve(dict(artifact, relative_dir=manifest["relative_dir"]))

    def export_case(self, case: dict, campaign: dict) -> Path:
        case_id = _safe_id(case["id"])
        completed = [e for e in case["episodes"] if e["status"] == "completed" and e.get("artifact_manifest")]
        if not completed:
            raise ArtifactError("Case has no completed evidence to export")
        with tempfile.TemporaryDirectory(prefix="case_", dir=self.root / "staging") as temporary:
            directory = Path(temporary)
            write_json(directory / "spec.json", campaign["spec"])
            # Keep all outcomes (including errors); copy every available episode payload.
            portable_case = {k: v for k, v in case.items() if k not in ("episodes", "spec")}
            portable_episodes = []
            for episode in case["episodes"]:
                portable_episodes.append({k: episode.get(k) for k in ("id", "phase", "request", "result", "status", "outcome", "config_hash")})
            portable_case["episodes"] = portable_episodes
            write_json(directory / "case.json", portable_case)
            write_json(directory / "budget.json", campaign["budget"])
            episode_manifests = []
            for episode in completed:
                manifest = episode["artifact_manifest"]
                self.verify_episode(manifest)
                episode_dir = directory / "episodes" / episode["id"]
                episode_dir.mkdir(parents=True)
                portable_files = []
                for artifact in manifest["files"]:
                    source = self.resolve(dict(artifact, relative_dir=manifest["relative_dir"]))
                    shutil.copyfile(source, episode_dir / artifact["path"])
                    portable_files.append({k: artifact[k] for k in ("path", "role", "sha256", "size")})
                portable_manifest = {"schema_version": SCHEMA_VERSION, "episode_id": episode["id"],
                                     "backend": campaign["backend"], "files": portable_files}
                write_json(episode_dir / "manifest.json", portable_manifest)
                episode_manifests.append(f"episodes/{episode['id']}/manifest.json")
            label = "SYNTHETIC SOFTWARE VALIDATION - NOT ROBOT EVIDENCE" if campaign["backend"] == "synthetic" else "Recorded robot simulation evidence"
            rows = "".join(f"<tr><td>{html.escape(e['id'])}</td><td>{e['state_id']}</td><td>{html.escape(e['condition'])}</td><td>{html.escape(str(e['outcome']))}</td></tr>" for e in case["episodes"])
            (directory / "report.html").write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><title>FailureForge case</title><style>body{{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #ddd}}table{{width:100%}}</style><h1>FailureForge case</h1><p>{label}</p><p>Case {case_id}. Outcome agreement is measured per execution; no cross-hardware exactness is claimed.</p><table><tr><th>Episode</th><th>State</th><th>Condition</th><th>Outcome</th></tr>{rows}</table></html>', encoding="utf-8")
            (directory / "reproduction.md").write_text(
                f"# Reproducing this case\n\n{label}\n\nInspect without models: `failureforge inspect-bundle PATH.zip`.\n"
                "Every episode has its own spec, initial state, outcome, trace and timestamps. Robot episodes include both camera recordings.\n"
                "Fresh inference requires the pinned Linux robotics environment and passed qualification gates documented in docs/robotics-setup.md.\n"
                "Use `failureforge rerun-bundle PATH.zip` on the qualified execution host; this allocates a fresh reference/changed pair for the selected case.\n"
                "Synthetic cases use `--backend synthetic` and establish software behavior only. Matching seeds do not guarantee identical outcomes across hardware.\n",
                encoding="utf-8")
            notice = Path(__file__).resolve().parents[2] / "THIRD_PARTY_NOTICES.md"
            (directory / "THIRD_PARTY_NOTICES.md").write_text(notice.read_text(encoding="utf-8") if notice.exists() else "LIBERO, MuJoCo, LeRobot and SmolVLA are third-party components. Model weights are not included. Refer to the pinned upstream terms before redistributing assets.\n", encoding="utf-8")
            files = [{"path": p.relative_to(directory).as_posix(), "sha256": digest(p), "size": p.stat().st_size} for p in sorted(directory.rglob("*")) if p.is_file()]
            manifest = {"schema_version": SCHEMA_VERSION, "case_id": case_id, "backend": campaign["backend"], "created_at": utc_now(),
                        "evidence_kind": "synthetic_diagnostic" if campaign["backend"] == "synthetic" else "robot_simulation",
                        "episode_manifests": episode_manifests, "files": files}
            write_json(directory / "manifest.json", manifest)
            all_files = files + [{"path": "manifest.json", "sha256": digest(directory / "manifest.json")}]
            (directory / "checksums.sha256").write_text("".join(f"{f['sha256']}  {f['path']}\n" for f in all_files), encoding="utf-8")
            snapshot = digest(directory / "manifest.json")[:16]
            target = self.root / "exports" / f"{case_id}_{snapshot}.zip"
            pending = directory / "bundle.zip"
            with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for file in sorted(directory.rglob("*")):
                    if file.is_file() and file != pending:
                        archive.write(file, file.relative_to(directory).as_posix())
            inspect_bundle(pending)
            os.replace(pending, target)
            return target


def _read_member(archive, name, limit):
    if archive.getinfo(name).file_size > limit:
        raise ArtifactError(f"Archive member exceeds size limit: {name}")
    # Bound individual decompressor calls even if a malicious ZIP lies about its
    # central-directory size; ZipFile.read() otherwise requests an unbounded read.
    result = io.BytesIO()
    with archive.open(name) as stream:
        for block in iter(lambda: stream.read(64 * 1024), b""):
            if result.tell() + len(block) > limit:
                raise ArtifactError(f"Archive member exceeds expansion limit: {name}")
            result.write(block)
    return result.getvalue()


def _json_object(archive, name, limit=MAX_JSON_BYTES):

    def unique_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ArtifactError(f"Duplicate JSON key: {name}")
            value[key] = item
        return value

    value = json.loads(_read_member(archive, name, limit), object_pairs_hook=unique_keys)
    if not isinstance(value, dict):
        raise ArtifactError(f"Expected JSON object: {name}")
    canonical_json(value)  # Reject NaN and infinity, including in nested metadata.
    return value


def _file_records(value, label):
    if not isinstance(value, list) or not value or len(value) > 4096:
        raise ArtifactError(f"Invalid file list: {label}")
    result = {}
    for item in value:
        if not isinstance(item, dict):
            raise ArtifactError(f"Invalid file record: {label}")
        name = item.get("path")
        safe_relative(name)
        if name in result:
            raise ArtifactError(f"Duplicate manifest path: {label}")
        if (type(item.get("size")) is not int or item["size"] < 0
                or not isinstance(item.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise ArtifactError(f"Invalid size or checksum record: {label}")
        result[name] = item
    return result


def _identity(value, backend, label, *, required_backend=False, required_schema=False):
    if not isinstance(value, dict):
        raise ArtifactError(f"Expected object: {label}")
    if (required_schema or "schema_version" in value) and value.get("schema_version") != SCHEMA_VERSION:
        raise ArtifactError(f"Unsupported schema: {label}")
    if (required_backend or "backend" in value) and value.get("backend") != backend:
        raise ArtifactError(f"Backend mismatch: {label}")
    evidence = "robot_simulation" if backend == "libero" else "synthetic_diagnostic"
    if "evidence_kind" in value and value["evidence_kind"] != evidence:
        raise ArtifactError(f"Evidence kind mismatch: {label}")


def _without_retry(value):
    # Retry bookkeeping is persisted by the scheduler, but is not passed to a runner.
    return {key: item for key, item in value.items() if key != "_retry"}


def _validate_episode(archive, manifest_path, episode, backend, top_files, names):
    episode_id = _safe_id(episode["id"])
    prefix = f"episodes/{episode_id}/"
    if manifest_path != prefix + "manifest.json":
        raise ArtifactError("Episode manifest path does not match its identity")
    manifest = _json_object(archive, manifest_path, 2 * 1024**2)
    _identity(manifest, backend, manifest_path, required_backend=True, required_schema=True)
    if manifest.get("episode_id") != episode_id:
        raise ArtifactError("Episode identity mismatch")
    files = _file_records(manifest.get("files"), manifest_path)
    required = REQUIRED | ({"main.mp4", "wrist.mp4"} if backend == "libero" else set())
    if missing := required - files.keys():
        raise ArtifactError(f"Episode lacks required files: {', '.join(sorted(missing))}")
    expected_names = {prefix + name for name in files} | {manifest_path}
    if {name for name in names if name.startswith(prefix)} != expected_names:
        raise ArtifactError("Episode manifest does not exactly describe its payloads")
    for name, item in files.items():
        relative = safe_relative(name)
        if len(relative.parts) != 1 or name in ("manifest.json", "checksums.sha256"):
            raise ArtifactError("Invalid episode payload path")
        if not isinstance(item.get("role"), str) or item["role"] != ROLES.get(name, relative.stem):
            raise ArtifactError(f"Invalid or missing artifact role: {name}")
        record = top_files.get(prefix + name)
        if record is None or any(item[key] != record[key] for key in ("sha256", "size")):
            raise ArtifactError("Nested episode checksum record disagrees with bundle manifest")
        if name in {"main.mp4", "wrist.mp4"} and item["size"] == 0:
            raise ArtifactError("Camera recording is empty")

    payloads = {name: _json_object(archive, prefix + name) for name in files if name.endswith(".json")}
    for name, value in payloads.items():
        _identity(value, backend, prefix + name)
    spec, outcome = payloads["spec.json"], payloads["outcome.json"]
    _identity(outcome, backend, prefix + "outcome.json", required_backend=True)
    request = episode.get("request")
    if not isinstance(request, dict) or _without_retry(request) != _without_retry(spec):
        raise ArtifactError("Episode spec differs from the case request")
    _identity(request, backend, "case episode request")
    result = episode.get("result")
    if not isinstance(result, dict) or result != outcome or episode.get("outcome") != outcome.get("outcome"):
        raise ArtifactError("Episode outcome differs from the case result")
    if (outcome.get("outcome") not in VALID_OUTCOMES or type(outcome.get("task_success")) is not bool
            or outcome["task_success"] != (outcome["outcome"] == "success")
            or type(outcome.get("steps")) is not int or not 0 <= outcome["steps"] <= 280
            or type(outcome.get("elapsed_seconds")) not in (int, float) or outcome["elapsed_seconds"] < 0):
        raise ArtifactError("Invalid completed episode outcome")
    metadata = outcome.get("metadata")
    if metadata is not None:
        _identity(metadata, backend, "episode result metadata")
        if "engine" in metadata and metadata["engine"] != backend:
            raise ArtifactError("Engine/backend mismatch in outcome metadata")
    environment = payloads["environment.json"]
    if "request" in environment and environment["request"] != spec:
        raise ArtifactError("Environment request differs from episode spec")
    # The real runner's environment and task identity omit a top-level backend;
    # check their existing task fields without inventing a provenance requirement.
    identity = payloads["task_identity.json"]
    if "state_id" in identity and identity["state_id"] != spec.get("state_id"):
        raise ArtifactError("Task identity state differs from episode spec")
    if isinstance(environment.get("task"), dict):
        for key in ("suite", "task_id", "task_order_index", "name"):
            if key in identity and key in environment["task"] and identity[key] != environment["task"][key]:
                raise ArtifactError("Environment and episode task identities differ")
    scene = payloads["scene_change.json"]
    scene_request = scene.get("requested", scene.get("scene_change"))
    if scene_request is not None and scene_request != spec.get("scene_change"):
        raise ArtifactError("Scene-change payload differs from episode spec")


def _inspect_bundle(path: str | Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 4096 or sum(e.file_size for e in entries) > 2 * 1024**3:
            raise ArtifactError("Bundle exceeds file-count or expansion limit")
        names = [e.filename for e in entries]
        if len(set(names)) != len(names):
            raise ArtifactError("Bundle contains duplicate paths")
        for entry in entries:
            relative = safe_relative(entry.filename)
            if stat.S_ISLNK(entry.external_attr >> 16) or entry.is_dir() or entry.flag_bits & 1 or relative.suffix not in SAFE_SUFFIXES:
                raise ArtifactError("Unexpected bundle content")
            if entry.file_size > 512 * 1024**2 or entry.file_size / max(1, entry.compress_size) > 1000:
                raise ArtifactError("Archive entry exceeds expansion limits")
        if not {"manifest.json", "checksums.sha256", "case.json", "spec.json"}.issubset(names):
            raise ArtifactError("Missing required bundle metadata")
        manifest = _json_object(archive, "manifest.json", 2 * 1024**2)
        backend = manifest.get("backend")
        if backend not in ("synthetic", "libero"):
            raise ArtifactError("Unsupported bundle backend")
        _identity(manifest, backend, "bundle manifest", required_schema=True, required_backend=True)
        evidence = "robot_simulation" if backend == "libero" else "synthetic_diagnostic"
        if manifest.get("evidence_kind") != evidence:
            raise ArtifactError("Bundle evidence kind mismatch")
        _safe_id(manifest.get("case_id"))
        files = _file_records(manifest.get("files"), "bundle manifest")
        if set(files) | {"manifest.json", "checksums.sha256"} != set(names) or set(files) & {"manifest.json", "checksums.sha256"}:
            raise ArtifactError("Manifest does not exactly describe the archive")
        for file in files.values():
            if archive.getinfo(file["path"]).file_size != file["size"]:
                raise ArtifactError("File size mismatch")
            actual = hashlib.sha256()
            with archive.open(file["path"]) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    actual.update(block)
            if actual.hexdigest() != file["sha256"]:
                raise ArtifactError(f"Checksum mismatch: {file['path']}")
        if archive.getinfo("checksums.sha256").file_size > 2 * 1024**2:
            raise ArtifactError("Checksum list exceeds limit")
        checksums = _read_member(archive, "checksums.sha256", 2 * 1024**2).decode("utf-8").splitlines()
        expected_checksums = {f["path"]: f["sha256"] for f in files.values()}
        expected_checksums["manifest.json"] = hashlib.sha256(_read_member(archive, "manifest.json", 2 * 1024**2)).hexdigest()
        try:
            parsed = dict(line.split("  ", 1)[::-1] for line in checksums)
        except ValueError as exc:
            raise ArtifactError("Malformed checksum file") from exc
        if parsed != expected_checksums or len(checksums) != len(expected_checksums):
            raise ArtifactError("Checksum list mismatch")

        spec, case = _json_object(archive, "spec.json"), _json_object(archive, "case.json")
        _identity(spec, backend, "campaign spec", required_schema=True, required_backend=True)
        CampaignSpec.model_validate(spec)
        _identity(case, backend, "case", required_backend=True)
        if case.get("id") != manifest["case_id"]:
            raise ArtifactError("Case identity differs from bundle manifest")
        episodes = case.get("episodes")
        if not isinstance(episodes, list) or not episodes:
            raise ArtifactError("Case has no episode records")
        by_id = {}
        for episode in episodes:
            if not isinstance(episode, dict):
                raise ArtifactError("Malformed case episode")
            identifier = _safe_id(episode.get("id"))
            if identifier in by_id:
                raise ArtifactError("Duplicate case episode identity")
            _identity(episode, backend, "case episode")
            for key in ("request", "result"):
                if episode.get(key) is not None:
                    _identity(episode[key], backend, f"case episode {key}")
            by_id[identifier] = episode
        completed = {identifier: episode for identifier, episode in by_id.items() if episode.get("status") == "completed"}
        if not completed:
            raise ArtifactError("Bundle has no completed episode evidence")
        episode_manifests = manifest.get("episode_manifests")
        if not isinstance(episode_manifests, list) or not all(isinstance(name, str) for name in episode_manifests):
            raise ArtifactError("Invalid episode manifest list")
        expected_manifests = {f"episodes/{identifier}/manifest.json" for identifier in completed}
        if set(episode_manifests) != expected_manifests or len(episode_manifests) != len(expected_manifests):
            raise ArtifactError("Episode manifests do not exactly match completed case entries")
        if {name.split("/")[1] for name in names if name.startswith("episodes/")} != set(completed):
            raise ArtifactError("Bundle episode directories do not match completed case entries")
        for identifier, episode in completed.items():
            _validate_episode(archive, f"episodes/{identifier}/manifest.json", episode, backend, files, names)
        for name in names:
            if name.endswith(".npz"):
                if archive.getinfo(name).file_size > MAX_NUMPY_BYTES:
                    raise ArtifactError("Numerical archive exceeds size limit")
                _validate_numpy(io.BytesIO(_read_member(archive, name, MAX_NUMPY_BYTES)))
        return {"valid": True, "schema_version": SCHEMA_VERSION, "case_id": manifest["case_id"],
                "backend": manifest["backend"], "evidence_kind": manifest["evidence_kind"], "file_count": len(entries),
                "manifest": manifest, "case": case, "spec": spec}


def inspect_bundle(path: str | Path) -> dict:
    """Validate a portable bundle, including nested evidence, without extracting it."""
    try:
        return _inspect_bundle(path)
    except ArtifactError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, EOFError, OverflowError,
            RecursionError, zipfile.BadZipFile, RuntimeError, NotImplementedError, struct.error,
            zlib.error, lzma.LZMAError) as exc:
        raise ArtifactError(f"Malformed artifact bundle: {exc}") from exc
