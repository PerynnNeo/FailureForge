"""Matched search-method reports from a consistent, read-only database snapshot."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import CampaignSpec, Contract


class StudyManifest(Contract):
    backend: Literal["synthetic", "libero"]
    seeds: list[Annotated[int, Field(strict=True, ge=0, le=2**31 - 1)]] = Field(min_length=1)
    campaigns: dict[Literal["random", "sobol", "sobol_local_mix"], list[str | None]] = Field(min_length=2)

    @model_validator(mode="after")
    def check_matrix(self):
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("Study seeds must be unique")
        seen = set()
        for method, ids in self.campaigns.items():
            if len(ids) != len(self.seeds):
                raise ValueError(f"{method} needs one campaign ID or null for each seed")
            for identifier in ids:
                if identifier is None:
                    continue
                if not identifier.strip() or identifier in seen:
                    raise ValueError("Assigned campaign IDs must be nonblank and unique")
                seen.add(identifier)
        return self


def _read_run(db, identifier, method, seed, backend):
    row = db.execute("SELECT spec FROM campaigns WHERE id=?", (identifier,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown campaign {identifier}. Use null for an unassigned study slot.")
    spec = CampaignSpec.model_validate_json(row["spec"])
    if (spec.backend, spec.method, spec.seed) != (backend, method, seed):
        raise ValueError(f"{identifier} does not match the declared backend, method and seed")
    job = db.execute("SELECT id,status,error FROM jobs WHERE campaign_id=? AND kind='search'", (identifier,)).fetchone()
    if job is None:
        raise ValueError(f"{identifier} has no search job")
    candidates = db.execute(
        "SELECT proposal_index,score,episode_ids FROM candidates "
        "WHERE campaign_id=? AND status='completed' ORDER BY proposal_index", (identifier,)
    ).fetchall()
    failing = [candidate for candidate in candidates if candidate["score"] > 0]
    first = failing[0] if failing else None
    # Reservation order breaks timestamp ties, and includes failed attempts charged before discovery.
    attempts = db.execute(
        "SELECT id,phase,status,outcome,json_extract(result,'$.elapsed_seconds') AS seconds,"
        "json_extract(result,'$.metadata.environment_fingerprint') AS fingerprint FROM episodes "
        "WHERE job_id=? ORDER BY rowid", (job["id"],)
    ).fetchall()
    search = [attempt for attempt in attempts if attempt["phase"] == "search"]
    to_first = None
    if first is not None:
        paired = set(json.loads(first["episode_ids"]))
        positions = [i for i, attempt in enumerate(search, 1) if attempt["id"] in paired]
        if len(positions) != len(spec.state_ids):
            raise ValueError(f"{identifier} has incomplete evidence for its first failing candidate")
        to_first = max(positions)
    fingerprints = set()
    if backend == "libero":
        fingerprints = {a["fingerprint"] for a in attempts if a["status"] == "completed"}
        if None in fingerprints or "" in fingerprints:
            raise ValueError(f"{identifier} has a completed LIBERO episode with no environment fingerprint")
    outcome = "incomplete"
    if job["status"] == "succeeded":
        if len(candidates) != spec.candidate_count:
            raise ValueError(f"{identifier} succeeded with an incomplete candidate bank")
        outcome = "found" if failing else "no_find"
    return {
        "campaign_id": identifier, "method": method, "seed": seed, "search_status": job["status"],
        "outcome": outcome, "search_error": job["error"], "completed_candidates": len(candidates),
        "failing_candidates": len(failing),
        "first_failing_candidate_number": first["proposal_index"] + 1 if first is not None else None,
        "search_attempts_to_first_failing_candidate": to_first,
        "baseline_attempts": sum(a["phase"] == "baseline" for a in attempts), "search_attempts": len(search),
        "attempt_errors_by_outcome": dict(Counter(a["outcome"] for a in attempts if a["status"] == "error")),
        "reserved_attempts": sum(a["status"] == "reserved" for a in attempts),
        "completed_search_episode_seconds": sum(a["seconds"] for a in search if a["status"] == "completed"),
    }, spec.model_dump(mode="json", exclude={"method", "seed", "name"}), fingerprints


def study_report(database: Path, manifest: StudyManifest) -> dict:
    runs = []
    summaries = []
    shared = None
    fingerprints = set()
    paired = set(manifest.seeds)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("Study reporting requires FailureForge database schema 1")
        for method, ids in manifest.campaigns.items():
            method_runs = []
            for seed, identifier in zip(manifest.seeds, ids, strict=True):
                if identifier is None:
                    run = {"campaign_id": None, "method": method, "seed": seed, "outcome": "missing"}
                else:
                    run, settings, identities = _read_run(db, identifier, method, seed, manifest.backend)
                    if shared is not None and settings != shared:
                        differences = ", ".join(key for key in settings if settings[key] != shared[key])
                        raise ValueError(f"{identifier} has incompatible campaign settings: {differences}")
                    shared = settings
                    fingerprints.update(identities)
                method_runs.append(run)
            runs.extend(method_runs)
            counts = Counter(run["outcome"] for run in method_runs)
            paired.intersection_update(run["seed"] for run in method_runs if run["outcome"] in ("found", "no_find"))
            summaries.append({"method": method, "planned": len(ids), "completed": counts["found"] + counts["no_find"],
                              **{key: counts[key] for key in ("found", "no_find", "incomplete", "missing")}})
    if len(fingerprints) > 1:
        raise ValueError("Cannot compare LIBERO runs with different recorded environment fingerprints")
    return {"schema_version": "1.0", "backend": manifest.backend,
            "evidence_kind": "synthetic_diagnostic" if manifest.backend == "synthetic" else "robot_simulation",
            "shared_campaign_settings": shared, "environment_fingerprint": next(iter(fingerprints), None),
            "fully_matched_completed_seeds": [s for s in manifest.seeds if s in paired], "methods": summaries, "runs": runs}


def study_markdown(report: dict) -> str:
    lines = ["# FailureForge search study", "", f"This report uses `{report['evidence_kind']}` evidence.", "",
             "| Method | Planned | Completed | Found a failure | No find | Incomplete | Missing |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for method in report["methods"]:
        lines.append("| {method} | {planned} | {completed} | {found} | {no_find} | {incomplete} | {missing} |".format(**method))
    seeds = ", ".join(map(str, report["fully_matched_completed_seeds"])) or "none"
    lines.extend(["", f"Fully matched completed seeds — {seeds}.", "",
                  "| Method | Seed | Campaign | Search state | Result | First failing candidate | Attempts to first failure | Baseline attempts | Search attempts |",
                  "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: |"])
    for run in report["runs"]:
        cells = [run.get(key) for key in ("method", "seed", "campaign_id", "search_status", "outcome",
                 "first_failing_candidate_number", "search_attempts_to_first_failing_candidate", "baseline_attempts", "search_attempts")]
        lines.append("| " + " | ".join("—" if value is None else str(value) for value in cells) + " |")
    return "\n".join(lines)
