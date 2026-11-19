"""Read-only camera previews for reviewed, completed qualification references."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response

from .contracts import VALID_OUTCOMES


def qualification_report(directory: Path):
    path = directory / "qualification.json"
    try:
        if path.resolve() != path or not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError):
        return None
    return value if isinstance(value, dict) else None


def _references(directory):
    report = qualification_report(directory) or {}
    if report.get("qualified") is not True or report.get("scene_review_approved") is not True:
        return {}, {}
    evidence, review = report.get("evidence_sha256"), report.get("scene_review")
    if not isinstance(evidence, dict) or not evidence or not isinstance(review, dict):
        raise HTTPException(409, "Qualification evidence is incomplete")
    # Use the same attestation encoding as the target-host qualification worker.
    from .simulation.profile import json_hash
    if (report.get("protocol") != "qualification-v1" or report.get("schema_version") != "1.0"
            or review.get("evidence_hash") != json_hash(evidence)):
        raise HTTPException(409, "Qualification evidence does not match the recorded scene review")
    records = {}
    attempts, states = report.get("attempts"), report.get("state_ids")
    if not isinstance(attempts, list) or not isinstance(states, list):
        raise HTTPException(409, "Qualification reference inventory is incomplete")
    for attempt in attempts:
        if not isinstance(attempt, dict) or attempt.get("status") != "completed":
            continue
        state, seed, result = attempt.get("state_id"), attempt.get("seed"), attempt.get("result")
        if (type(state) is not int or state < 0 or state not in states or type(seed) is not int
                or attempt.get("path") != f"reference-{state:03d}" or not isinstance(result, dict)
                or result.get("backend") != "libero" or not isinstance(result.get("outcome"), str)
                or result["outcome"] not in VALID_OUTCOMES
                or type(result.get("steps")) is not int or not 0 <= result["steps"] <= 280):
            continue
        if state in records:
            raise HTTPException(409, "Qualification contains duplicate completed reference IDs")
        folder = directory / f"reference-{state:03d}"
        cameras = {}
        for view in ("main", "wrist"):
            path = folder / (view + ".mp4")
            expected = evidence.get(f"{folder.name}/{view}.mp4")
            try:
                present = path.resolve() == path and path.is_file()
            except (OSError, RuntimeError):
                present = False
            if present and isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected):
                cameras[view] = f"/api/qualification/references/{state}/{view}"
        if len(cameras) == 2:
            records[state] = {"state_id": state, "seed": seed, "outcome": result["outcome"],
                              "steps": result["steps"], "cameras": cameras}
    return records, evidence


def _video_response(data, requested_range):
    size = len(data)
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-store"}
    if requested_range:
        match = re.fullmatch(r"bytes=(\d{0,18})-(\d{0,18})", requested_range.strip())
        if match and any(match.groups()):
            left, right = match.groups()
            start = int(left) if left else max(0, size - int(right))
            end = min(int(right), size-1) if left and right else size-1
            if start > end or start >= size:
                return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
            return Response(data[start:end+1], status_code=206, media_type="video/mp4",
                            headers={**headers, "Content-Range": f"bytes {start}-{end}/{size}"})
    return Response(data, media_type="video/mp4", headers=headers)


def qualification_router(directory: Path):
    router = APIRouter(prefix="/api/qualification/references", tags=["qualification evidence"])

    @router.get("")
    def list_references():
        records, _ = _references(directory)
        return {"references": [records[key] for key in sorted(records)]}

    @router.get("/{state_id}/{camera}", response_class=Response, responses={200: {"content": {"video/mp4": {}}},
                                                                           206: {"content": {"video/mp4": {}}}})
    def camera_reference(state_id: int, camera: Literal["main", "wrist"], range_header: str | None = Header(None, alias="Range")):
        records, evidence = _references(directory)
        if state_id not in records:
            raise HTTPException(404, "Reviewed reference recording unavailable")
        relative = f"reference-{state_id:03d}/{camera}.mp4"
        path = directory / relative
        if path.resolve() != path:
            raise HTTPException(404, "Reviewed reference recording unavailable")
        try:
            # Each qualified clip contains at most 281 RGB 256x256 frames. Bound
            # allocation even if a previously published MP4 has been replaced.
            with path.open("rb") as stream:
                data = stream.read(64 * 1024**2 + 1)
        except OSError as exc:
            raise HTTPException(404, "Reviewed reference recording unavailable") from exc
        if not data or len(data) > 64 * 1024**2 or hashlib.sha256(data).hexdigest() != evidence[relative]:
            raise HTTPException(409, "Recording differs from the scene-reviewed qualification evidence")
        # Serve the same bytes whose hash was checked, including on seek/range requests.
        return _video_response(data, range_header)

    return router
