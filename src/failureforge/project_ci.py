"""Submit revision-pinned project checks through the HTTP API and report CI decisions."""
from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .project_validity import assessment_error


REPORT = "failureforge-project-ci-v1"


def configure(sub):
    parser = sub.add_parser("project-ci", help="Submit project analyses, wait for results, and compare a baseline")
    parser.add_argument("project_id")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec", type=Path, help="Single test or suite definition in JSON")
    source.add_argument("--rerun", type=Path, help="Rerun immutable definitions referenced by a prior CI report")
    source.add_argument("--rerun-suite", help="Rerun all immutable definitions in a saved suite ID")
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--baseline", type=Path, help="Compare the supplied specification with a saved CI report")
    baseline.add_argument("--baseline-suite", help="Compare the supplied specification with an existing suite ID")
    parser.add_argument("--expected-revision", type=int, help="Fence submission to this exact project revision")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="Project API origin")
    parser.add_argument("--timeout", type=float, default=300, help="Overall deadline in seconds")
    parser.add_argument("--poll-interval", type=float, default=1, help="Seconds between polls")
    parser.add_argument("--idempotency-key", help="Reuse this key to reconnect to a submission after an interruption")
    parser.add_argument("--allow-measurement-only", action="store_true", help="Accept completed checks without a pass/fail rule")


class NoRedirect(HTTPRedirectHandler):
    # Keep credentials scoped to the configured API origin.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    def __init__(self, url, token):
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment):
            raise ValueError("Supply an HTTP(S) API URL without credentials, query or fragment")
        if token and parts.scheme == "http" and parts.hostname != "localhost":
            try:
                local = ipaddress.ip_address(parts.hostname).is_loopback
            except ValueError:
                local = False
            if not local:
                raise ValueError("Use HTTPS or a loopback tunnel when sending a bearer token")
        self.origin = url.rstrip("/")
        self.headers = {"Accept": "application/json"}
        if token:
            self.headers["Authorization"] = "Bearer " + token
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, *, data=None, key=None, timeout):
        headers = dict(self.headers)
        body = None
        if data is not None:
            body = json.dumps(data, allow_nan=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        req = Request(self.origin + path, method=method, headers=headers, data=body)
        try:
            with self.opener.open(req, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            with exc:
                try:
                    detail = json.loads(exc.read(8192)).get("detail")
                except (ValueError, AttributeError):
                    detail = None
            raise ValueError(f"Project API returned HTTP {exc.code}: {str(detail or exc.reason)[:1500]}") from exc
        except URLError as exc:
            raise OSError(f"Project API connection failed: {exc.reason}") from exc


def _json_file(path):
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return obj


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", value):
        raise ValueError("Invalid project or analysis identifier")
    return value


def _definitions(entries):
    if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
        raise ValueError("A project suite requires 1 to 16 tests")
    keys = []
    for test in entries:
        if (not isinstance(test, dict) or test.keys() - {"label", "adapter", "inputs", "bindings"}
                or any(not isinstance(test.get(k), str) or not test[k].strip() for k in ("label", "adapter"))
                or not isinstance(test.get("inputs"), dict) or not isinstance(test.get("bindings", {}), dict)):
            raise ValueError("Each test requires label, adapter, inputs, and optionally a bindings object")
        test["label"], test["adapter"] = test["label"].strip(), test["adapter"].strip()
        keys.append((test["label"], test["adapter"]))
    if len(set(keys)) != len(keys):
        raise ValueError("Use a distinct label and adapter combination for every check")
    return keys


def _saved_runs(path, suite_id, project, request, base):
    if path:
        saved = _json_file(path)
        if saved.get("format") != REPORT or saved.get("project_id") != project:
            raise ValueError("The baseline must be a project-ci report for this project")
        suite_id = saved.get("suite_id")
    records = request("GET", f"{base}/analysis-suite/{_id(suite_id)}")["runs"]
    if any(row["suite_id"] != suite_id or row["project_id"] != project for row in records):
        raise ValueError("The baseline suite does not belong to this project")
    if path and [entry["id"] for entry in saved["runs"]] != [record["id"] for record in records]:
        raise ValueError("The baseline report does not match the complete frozen suite membership")
    return records


def _summary(row):
    result = row.get("result") or {}
    reason = row.get("assessment_error") or assessment_error(result)
    passed = None if reason else result.get("passed", result.get("summary", {}).get("validation_passed"))
    if passed is not None and type(passed) is not bool:
        raise ValueError("The project API returned a malformed pass/fail value")
    return {**{k: row.get(k) for k in ("id", "label", "adapter", "project_revision", "status", "evidence_hash", "error")},
            "passed": passed, "assessment_error": reason, "summary": result.get("summary", result.get("metrics", {})),
            "binding_evidence": row.get("binding_evidence", {})}


def execute(args, *, api=None):
    report = {"format": REPORT, "project_id": args.project_id, "suite_id": None, "runs": [], "comparisons": []}
    token = os.environ.get("FAILUREFORGE_API_TOKEN")
    try:
        project = _id(args.project_id)
        replay = args.rerun or args.rerun_suite
        if replay and (args.baseline or args.baseline_suite):
            raise ValueError("A frozen rerun already compares against its original suite")
        if any(not math.isfinite(v) or v <= 0 for v in (args.timeout, args.poll_interval)):
            raise ValueError("Timeout and polling interval must be finite and positive")
        deadline = time.monotonic() + args.timeout
        api = api or Api(args.api_url, token)

        def remaining():
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("CI deadline reached; submitted runs retain their IDs and continue on the server")
            return left

        def request(method, path, **kwargs):
            return api.request(method, path, timeout=remaining(), **kwargs)

        base = f"/api/projects/{project}"
        current = request("GET", base)["revision"]
        saved = _saved_runs(args.rerun or args.baseline, args.rerun_suite or args.baseline_suite, project,
                            request, base) if replay or args.baseline or args.baseline_suite else []
        # Old service responses predate parameter binding and contain literal inputs only.
        saved_defs = [r.get("definition") or {k: r[k] for k in ("label", "adapter", "inputs")} for r in saved]
        baseline = dict(zip(_definitions(saved_defs), saved)) if saved else {}
        if replay:
            spec, definitions, suite = {}, saved_defs, len(saved_defs) > 1
        else:
            spec = _json_file(args.spec)
            suite = "tests" in spec
            if suite and spec.keys() - {"tests", "expected_revision"}:
                raise ValueError("Suite fields are tests and optional expected_revision")
            definitions = spec["tests"] if suite else [{k: v for k, v in spec.items() if k != "expected_revision"}]
        keys = _definitions(definitions)
        if baseline and baseline.keys() != set(keys):
            raise ValueError("Baseline and candidate suite membership differ; match each label and adapter")
        expected = spec.get("expected_revision", current) if args.expected_revision is None else args.expected_revision
        # The API first checks the idempotency record, then fences fresh work to
        # the current revision. Let an explicit key reattach to an older snapshot.
        if (type(expected) is not int or expected < 1 or spec.get("expected_revision", expected) != expected
                or (expected != current and not args.idempotency_key)):
            raise ValueError(f"Expected revision is invalid, conflicting or stale; current revision is {current}")
        key = args.idempotency_key or str(uuid.uuid4())
        if not 8 <= len(key) <= 200 or not key.isascii() or not key.isprintable():
            raise ValueError("The idempotency key must contain 8 to 200 printable ASCII characters")
        report.update(project_revision=expected, idempotency_key=key)
        if suite:
            receipt = request("POST", base+"/analysis-suite", data={"expected_revision": expected, "tests": definitions}, key=key)
            records = receipt["runs"]
            report["suite_id"] = receipt["suite_id"]
        else:
            row = request("POST", base+"/analysis", data={"expected_revision": expected, **definitions[0]}, key=key)
            records, report["suite_id"] = [row], row["suite_id"]
        if [(r["label"], r["adapter"]) for r in records] != keys:
            raise ValueError("Project API receipt does not match the submitted test membership")
        report["runs"] = [_summary(row) for row in records]
        while any(row["status"] in ("queued", "running") for row in report["runs"]):
            for index, row in enumerate(report["runs"]):
                if row["status"] in ("queued", "running"):
                    record = request("GET", f"{base}/analysis/{_id(row['id'])}")
                    report["runs"][index] = _summary(record)
            if any(r["status"] in ("queued", "running") for r in report["runs"]):
                time.sleep(min(remaining(), args.poll_interval))
        for row in report["runs"]:
            if baseline:
                old = baseline[(row["label"], row["adapter"])]
                comparison = request("GET", f"{base}/analysis/{_id(old['id'])}/compare/{_id(row['id'])}")
                report["comparisons"].append(comparison)
        counts = Counter(row["status"] for row in report["runs"])
        report["status_counts"] = dict(counts)
        excluded = {"not_comparable"} if args.allow_measurement_only else {"not_comparable", "measurement_only"}
        if (any(row["status"] != "completed" or row["assessment_error"] for row in report["runs"])
                or any(row["outcome"] in excluded for row in report["comparisons"])
                or (not args.allow_measurement_only and any(row["passed"] is None for row in report["runs"]))):
            decision, code = "inconclusive", 2
        elif any(row["passed"] is False for row in report["runs"]):
            decision, code = "failed", 1
        else:
            decision, code = "accepted", 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        message = str(exc)
        report["error"] = message.replace(token, "[redacted]") if token else message
        decision, code = "inconclusive", 2
    report.update(decision=decision, exit_code=code)
    return report, code
