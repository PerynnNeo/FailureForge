"""Run the labelled, local CPU discovery example using the same HTTP API as the browser."""
import argparse
import hashlib
import http.client
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--fresh", action="store_true", help="Request a new model generation for the same reference.")
    parser.add_argument("--review-only", action="store_true", help="Generate suggestions for individual review instead of automatically simulating them.")
    parser.add_argument("--approve", metavar="SCENARIO_ID", help="Run this specific card after reviewing its premises and exact changes.")
    parser.add_argument("--review-note", default="", help="Record the operating assumptions you are approving for that card.")
    args = parser.parse_args()
    run_supported = not args.review_only and not args.approve

    def api(method, path, body=None, key=None):
        conn = http.client.HTTPConnection("127.0.0.1", args.port, timeout=30)
        raw = isinstance(body, bytes)
        headers = {"Content-Type": "application/octet-stream" if raw else "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        if token := os.environ.get("FAILUREFORGE_API_TOKEN"):
            headers["Authorization"] = "Bearer " + token
        try:
            conn.request(method, "/api" + path, body if raw or body is None else json.dumps(body), headers)
            response = conn.getresponse()
            value = json.loads(response.read())
            if response.status >= 400:
                raise SystemExit(f"HTTP {response.status}: {value.get('detail', value)}")
            return value
        finally:
            conn.close()

    def wait(load, done, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = load()
            if done(result):
                return result
            time.sleep(1.5)
        raise SystemExit("Timed out. The workbench retains the job and its status.")

    spec = {"name": "CPU demo · Cantilever loading shelf", "entry_stage": "cad", "analysis_type": "structural",
            "goal": "Carry parts on a narrow cantilever shelf during manual sorting.",
            "success_criteria": "Maximum deflection must stay within 0.10 mm during loading.",
            "notes": "Illustrative design supplied for the local FailureForge demo.",
            "parameters": [], "test_plans": []}
    task = ("At a repair station a technician temporarily sets small parts on this shelf while sorting them. "
            "The technician can use the whole shelf. Parts are moved by hand and the mounting stays fixed. "
            "Which ordinary handling situations could affect whether it meets its deflection limit?")
    created = api("POST", "/projects", spec, "cpu-discovery-demo-project-v1")
    project_id = created["id"]
    base = "/projects/" + project_id
    project = api("GET", base)
    if any(project[k] != spec[k] for k in ("name", "goal", "success_criteria", "analysis_type")):
        raise SystemExit("The example was edited. Open that project in the workbench to continue.")
    sample = Path(__file__).resolve().parents[1] / "apps/web/public/examples/beam-reference.json"
    raw = sample.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    asset = next((a for a in project["assets"] if a["sha256"] == sha and a["kind"] == "requirements"), None)
    if asset is None:
        qs = urlencode({"filename": sample.name, "kind": "requirements"})
        project = api("POST", base + "/assets?" + qs, raw)
        asset = next(a for a in project["assets"] if a["sha256"] == sha)
    revision = {"expected_revision": project["revision"]}
    scope = base + "/scenarios"
    receipt = api("POST", scope + "/import-reference", {**revision, "asset_id": asset["id"]},
                  f"demo-reference-{asset['id']}-{project['revision']}")

    def run(run_id):
        item = wait(lambda: api("GET", base + "/analysis/" + run_id),
                    lambda r: r["status"] not in ("running", "queued"), 90)
        if item["status"] != "completed":
            raise SystemExit(f"CPU run {run_id} ended as {item['status']}: {item.get('error')}")
        return item

    baseline = run(receipt["ids"][0])
    print(f"Reference {baseline['id']} completed.", flush=True)
    print(f"http://127.0.0.1:{args.port}/#/projects/{project_id}?tab=scenarios", flush=True)
    history = api("GET", scope)
    if not history["provider"]["available"]:
        raise SystemExit(history["provider"]["detail"])
    batches = history["batches"]
    if args.approve:
        batches = [b for b in batches if any(c["id"] == args.approve for c in b["candidates"])]
        if not batches or args.fresh:
            raise SystemExit("Choose an existing card for approval, without --fresh.")
    else:
        batches = [b for b in batches if b["run_supported"] == run_supported]
    batch = next((b for b in batches if b["baseline_run_id"] == baseline["id"] and b["task"] == task
                  and b["status"] in ("completed", "queued", "running")), None)
    if batch is None or args.fresh:
        batch = api("POST", scope + "/generate", {**revision, "task": task, "baseline_run_id": baseline["id"],
                    "run_supported": run_supported},
                    "demo-generate-" + uuid.uuid4().hex)
    batch_id = batch["id"]
    print(f"http://127.0.0.1:{args.port}/#/projects/{project_id}?tab=scenarios&generation={batch_id}", flush=True)
    if batch["status"] in ("queued", "running"):
        print(f"Waiting for local model {batch['model']}.", flush=True)
    batch = wait(lambda: next(b for b in api("GET", scope)["batches"] if b["id"] == batch_id),
                 lambda b: b["status"] not in ("running", "queued"), 900)
    if batch["status"] != "completed":
        raise SystemExit(batch["error"])
    if run_supported:
        report = wait(lambda: api("GET", scope + "/batches/" + batch_id + "/results"),
                      lambda item: not item["counts"]["pending"], 300)
        if report["execution_error"]:
            raise SystemExit(report["execution_error"])
        for row in report["rows"]:
            metric = row["measurement"]
            value = f"{metric['value']:.6g} {metric['unit']}" if metric else row["reason"]
            print(f"{row['state']:>16} | {row['title']} | {value}", flush=True)
        print("Batch counts:", report["counts"], flush=True)
        return
    for card in batch["candidates"]:
        draft = card["draft"]
        print(f"{card['id']} | {draft['title']}\n  {draft['hypothesis']}\n  Assumptions: {draft['assumptions']}", flush=True)
    if not args.approve:
        print("Review the proposals and run a supported case in the browser, or rerun with --approve SCENARIO_ID.")
        return
    for card in batch["candidates"]:
        if card["dismissed"] or card["id"] != args.approve:
            continue
        endpoint = scope + "/" + card["id"]
        preview = api("POST", endpoint + "/preview", {**revision, "confirmed": True})
        if preview["state"] != "ready":
            continue
        receipt = api("POST", endpoint + "/execute", {**revision, "confirmed": True,
                      "fingerprint": preview["fingerprint"], "review_note": args.review_note}, "demo-execute-" + card["id"])
        for role, identifier in zip(("Reference", "What-if"), receipt["runs"], strict=True):
            record = run(identifier)
            print(role, record["result"]["passed"], record["result"]["summary"], flush=True)
        return
    raise SystemExit("The requested card is unavailable for execution. Inspect the original batch in the workbench.")


if __name__ == "__main__":
    main()
