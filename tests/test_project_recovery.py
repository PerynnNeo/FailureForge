import sqlite3
import time

from failureforge.api import create_app
from failureforge.project_runs import ProjectRuns, ProjectTest
from failureforge.projects import ProjectSpec


def queued(tmp_path, count=1):
    app = create_app(tmp_path)
    runs = ProjectRuns(app.state.projects)
    project = runs.projects.create(ProjectSpec(name="Recovery fixture", entry_stage="prototype", analysis_type="thermal",
                                              goal="Exercise recovery", success_criteria="Preserve evidence"))["id"]
    tests = [ProjectTest(label=f"Check {n}", adapter="thermal_rod", inputs={}) for n in range(count)]
    ids = runs.submit(project, 1, tests, "recovery-fixture")["ids"]
    return runs, project, ids


def test_expired_owner_cannot_publish_before_recovery_or_after_new_claim(tmp_path):
    runs, project, (run,) = queued(tmp_path)
    row, stale_lease = runs._claim()
    with runs.store.connection(True) as db:
        db.execute("UPDATE project_runs SET expires=? WHERE id=?", (time.time()-1, run))
    stale = {"status": "completed", "result": {"passed": False}, "runtime": {}}
    runs._publish(row, stale_lease, stale)
    interrupted = runs.get(project, run)
    assert interrupted["status"] == "interrupted" and interrupted["finished_at"]
    assert interrupted["result"] is None and interrupted["evidence_hash"] is None

    runs.command(project, run, "resume")
    resumed_row, new_lease = runs._claim()
    assert new_lease != stale_lease
    runs._publish(row, stale_lease, stale)
    assert runs.get(project, run)["status"] == "running"
    runs._publish(resumed_row, new_lease, {"status": "completed", "result": {"passed": True}, "runtime": {}})
    completed = runs.get(project, run)
    assert completed["result"]["passed"] and completed["attempt"] == 2 and completed["evidence_hash"]


def test_sqlite_contention_during_claim_and_publish_does_not_stop_queue_or_rerun_solver(tmp_path, monkeypatch):
    runs, project, ids = queued(tmp_path, count=2)
    # Obtain the real SQLite BUSY exception, including its native result code.
    with sqlite3.connect(tmp_path/"busy.sqlite") as holding, sqlite3.connect(tmp_path/"busy.sqlite", timeout=0) as contender:
        holding.execute("BEGIN IMMEDIATE")
        try:
            contender.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            busy = exc
    attempts = {"_claim": 0, "_publish": 0}
    def fail_once(name):
        original = getattr(runs, name)
        def wrapped(*args):
            attempts[name] += 1
            if attempts[name] == 1:
                raise busy
            return original(*args)
        monkeypatch.setattr(runs, name, wrapped)
    fail_once("_claim")
    fail_once("_publish")
    executed = []
    def completed(row, lease):
        executed.append(row["id"])
        return {"status": "completed", "result": {"passed": True}, "runtime": {}}
    monkeypatch.setattr(runs, "_execute", completed)
    runs.start()
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and runs.get(project, ids[-1])["status"] != "completed":
            time.sleep(.02)
        assert executed == ids
        assert all(runs.get(project, run)["evidence_hash"] for run in ids)
        assert all(runs.get(project, run)["attempt"] == 1 for run in ids)
        assert runs.thread.is_alive()
    finally:
        runs.close()
