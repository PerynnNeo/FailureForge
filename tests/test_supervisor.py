"""Exercise actual spawned-process boundaries without importing robotics packages."""
import time

import pytest

from failureforge.worker import supervisor


def stalled_child(pipe, cancelled, options):
    pipe.recv()
    time.sleep(60)


def cooperative_child(pipe, cancelled, options):
    while True:
        request, directory = pipe.recv()
        if request.get("await_cancel"):
            cancelled.wait(5)
            pipe.send((True, {"outcome": "cancelled"}))
        else:
            pipe.send((True, {"outcome": "success", "state_id": request["state_id"]}))


def test_wall_time_watchdog_terminates_stuck_child(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, "_child", stalled_child)
    runner = supervisor.ProcessRunner("unused", "unused", timeout_seconds=0.3)
    started = time.monotonic()
    with pytest.raises(supervisor.RunnerProcessError, match="wall-time") as error:
        runner.run({}, tmp_path)
    assert error.value.code == "worker_lost"
    assert runner.process is None and runner.pipe is None
    assert time.monotonic() - started < 8


def test_worker_reuses_child_and_propagates_cancellation(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, "_child", cooperative_child)
    runner = supervisor.ProcessRunner("unused", "unused", timeout_seconds=10)
    try:
        assert runner.run({"state_id": 1}, tmp_path)["state_id"] == 1
        first_pid = runner.process.pid
        assert runner.run({"state_id": 2}, tmp_path)["state_id"] == 2
        assert runner.process.pid == first_pid
        assert runner.run({"await_cancel": True}, tmp_path, cancelled=lambda: True)["outcome"] == "cancelled"
    finally:
        runner.close()
    assert runner.process is None and runner.pipe is None


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_watchdog_timeout_rejected(timeout):
    with pytest.raises(ValueError, match="finite and positive"):
        supervisor.ProcessRunner("unused", "unused", timeout_seconds=timeout)
