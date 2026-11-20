"""Freeze a private reference checklist and audit a saved scenario discovery batch offline.

Before intake: freeze checklist.json lock.json
After the UI run: score checklist.json lock.json batch.json results.json review.json

Checklist fields: prototype, checklist_source, conditions [{id, description}].
Review fields: reviewer, interventions (list of descriptions), conditions [{id,
reason, candidate_id}]. Use null for a miss. To cite a suggestion add match
("equivalent" or "related") and quote an exact excerpt from the candidate draft.
A verbatim batch clarification may be supplied instead of a candidate.
For execution credit, additionally identify the actual controlled inputs:
controls = {"reference": {"field": value}, "variant": {"field": value}}.
Include every input changed between the reference and variant. Omit a field on
one side only if it is absent on that side of the saved plan.
For equivalent matches, origin may be "supplied", "unprompted" or "unknown"
according to the reviewer's audit of what was in the intake and baseline.

The lock detects edits and records local chronology. The reviewer judges semantic
equivalence to the published reference. Neither document is sent to the product.
"""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def load(path):
    return json.loads(path.read_bytes())


def required_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty text for {name}")
    return value


def indexed(rows, key):
    if not isinstance(rows, list):
        raise ValueError(f"Expected a list of rows with {key}")
    by_id = {}
    for row in rows:
        identifier = required_text(row[key], key)
        if identifier in by_id:
            raise ValueError(f"Duplicate {key}: {identifier}")
        by_id[identifier] = row
    return by_id


def read_checklist(path):
    raw = path.read_bytes()
    checklist = json.loads(raw)
    required_text(checklist["prototype"], "prototype")
    required_text(checklist["checklist_source"], "checklist_source")
    conditions = indexed(checklist["conditions"], "id")
    if not conditions:
        raise ValueError("An independent checklist needs at least one condition")
    for condition in conditions.values():
        required_text(condition["description"], "description")
    return checklist, hashlib.sha256(raw).hexdigest()


def freeze(checklist_path, lock_path):
    _, digest = read_checklist(checklist_path)
    lock = {"sha256": digest, "frozen_at": datetime.now(timezone.utc).isoformat()}
    with lock_path.open("x", encoding="utf-8") as handle:
        json.dump(lock, handle, indent=2)
        handle.write("\n")
    return lock


def instant(value):
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Pilot timestamps must include a timezone")
    return timestamp


def controls_match(claim, plan):
    if not isinstance(claim, dict) or set(claim) != {"reference", "variant"}:
        raise ValueError("A control claim requires both reference and variant inputs")
    left, right = claim["reference"], claim["variant"]
    if not isinstance(left, dict) or not isinstance(right, dict) or left == right:
        raise ValueError("Identify a concrete control difference between the two sides")
    if not all(isinstance((plan.get(role) or {}).get("inputs"), dict) for role in claim):
        raise ValueError("No compiled reference and variant inputs are available for this claim")
    fields = left.keys() | right.keys()
    for role, expected in claim.items():
        inputs = plan[role]["inputs"]
        for name in fields:
            if (name in inputs) != (name in expected):
                raise ValueError(f"Claimed {role} input {name} differs from the saved plan")
            if name in inputs:
                actual, claimed = inputs[name], expected[name]
                if actual != claimed or isinstance(actual, bool) != isinstance(claimed, bool):
                    raise ValueError(f"Claimed {role} input {name} differs from the saved plan")
    baseline, variant = plan["reference"]["inputs"], plan["variant"]["inputs"]
    changed_inputs = {key for key in baseline.keys() & variant.keys() if baseline[key] != variant[key]}
    changed_inputs.update(baseline.keys() ^ variant.keys())
    if changed_inputs - fields:
        raise ValueError("The saved comparison changed additional inputs omitted from the control claim")


def grade(condition, mapping, batch, candidates, outcomes):
    identifier = mapping["candidate_id"]
    reason = required_text(mapping["reason"], "review reason")
    row = {**condition, "review_reason": reason, "candidate_id": identifier}
    if identifier is None:
        if any(key in mapping for key in ("quote", "match", "controls")):
            raise ValueError("A suggestion or control claim requires a persisted candidate")
        if "clarification" in mapping:
            question = required_text(mapping["clarification"], "clarification")
            if question not in batch["clarifications"]:
                raise ValueError("Clarification is absent from the saved batch")
            return {**row, "coverage": "clarification_only", "clarification": question}
        return {**row, "coverage": "missed"}

    candidate, result = candidates[identifier], outcomes[identifier]
    quote = required_text(mapping["quote"], "quote")
    if not any(quote in (candidate["draft"].get(field) or "") for field in
               ("title", "hypothesis", "question", "missing_capability")):
        raise ValueError(f"Quote is absent from candidate {identifier}")
    match = mapping["match"]
    if match not in ("related", "equivalent"):
        raise ValueError("Match must be related or equivalent")
    origin = mapping.get("origin", "unknown")
    if origin not in ("unknown", "supplied", "unprompted"):
        raise ValueError("Invalid intake origin")
    state = result["state"]
    compiled = bool(candidate.get("execution")) or state == "ready"
    row.update(quote=quote, origin=origin, candidate_state=state, candidate_compiled=compiled,
               candidate_reason=result["reason"], coverage="related" if match == "related" else "proposed")
    if "controls" in mapping:
        if match != "equivalent":
            raise ValueError("Only an equivalent match can receive execution credit")
        controls_match(mapping["controls"], candidate.get("review") or {})
        row["controls"] = mapping["controls"]
        assessed = state in ("passed", "failed")
        measured = state == "measurement_only" and result.get("measurement") is not None
        if assessed or measured:
            ref, variant = result["reference_run_id"], result["variant_run_id"]
            suite = result["suite_id"]
            execution = candidate.get("execution") or {}
            if not (ref and variant and ref != variant and suite and suite == execution.get("suite_id")
                    and [ref, variant] == execution.get("runs")):
                raise ValueError("Assessed comparison lacks matching saved run and suite identifiers")
            row.update(coverage="simulated", reference_run_id=ref, variant_run_id=variant,
                       suite_id=suite, measurement=result["measurement"])
    return row


def score(checklist_path, lock, batch, results, review):
    checklist, digest = read_checklist(checklist_path)
    if digest != lock["sha256"]:
        raise ValueError("Reference checklist changed after freeze")
    if instant(lock["frozen_at"]) >= instant(batch["created_at"]):
        raise ValueError("Freeze the reference before starting the scenario batch")
    if batch["status"] != "completed" or results["generation_status"] != "completed":
        raise ValueError("Only a completed generation can be evaluated for discovery")
    if batch["id"] != results["batch_id"]:
        raise ValueError("Candidates and results belong to different batches")
    candidates = indexed(batch["candidates"], "id")
    outcomes = indexed(results["rows"], "candidate_id")
    if candidates.keys() != outcomes.keys():
        raise ValueError("The saved results must cover the same candidates as the batch")
    references = indexed(checklist["conditions"], "id")
    mappings = indexed(review["conditions"], "id")
    if mappings.keys() != references.keys():
        raise ValueError("Review every independent checklist condition exactly once")
    reviewer = required_text(review["reviewer"], "reviewer")
    interventions = review["interventions"]
    if not isinstance(interventions, list):
        raise ValueError("List the human interventions, or supply an empty list")
    for entry in interventions:
        required_text(entry, "intervention")
    rows = [grade(condition, mappings[key], batch, candidates, outcomes) for key, condition in references.items()]
    counts = Counter(row["coverage"] for row in rows)
    used = {row["candidate_id"] for row in rows}
    inventory = [{"candidate_id": key, "title": item["draft"]["title"],
                  "operation_id": item["draft"].get("operation_id"),
                  "fact_refs": item["draft"].get("fact_refs", []), "state": outcomes[key]["state"]}
                 for key, item in candidates.items()]
    return {"prototype": checklist["prototype"], "checklist_source": checklist["checklist_source"],
            "lock": lock, "batch_id": batch["id"], "generated_batch_started_at": batch["created_at"],
            "model": batch["model"], "digest": batch.get("digest"), "prompt_version": batch.get("prompt_version"),
            "candidate_pass_attribution": "First response, repair and registry-guided refinement are not distinguished in the saved candidate records.",
            "candidates": inventory, "task": batch["task"], "baseline_run_id": batch["baseline_run_id"],
            "reviewer": reviewer, "condition_count": len(rows),
            "coverage": {key: counts[key] for key in ("simulated", "proposed", "related", "clarification_only", "missed")},
            "conditions": rows, "unmatched_candidates": [key for key in candidates if key not in used],
            "interventions": interventions}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_subparsers(dest="mode", required=True)
    lock_cmd = modes.add_parser("freeze")
    report_cmd = modes.add_parser("score")
    for cmd in (lock_cmd, report_cmd):
        cmd.add_argument("checklist", type=Path)
        cmd.add_argument("lock", type=Path)
    for name in ("batch", "results", "review"):
        report_cmd.add_argument(name, type=Path)
    report_cmd.add_argument("--output", type=Path, help="Create a new JSON report at this path")
    args = parser.parse_args()
    try:
        if args.mode == "freeze":
            freeze(args.checklist, args.lock)
            return
        report = score(args.checklist, load(args.lock), load(args.batch), load(args.results), load(args.review))
        rendered = json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False)
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(rendered + "\n")
        else:
            print(rendered)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
