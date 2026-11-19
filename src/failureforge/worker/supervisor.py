"""Persistent child process isolates uninterruptible CUDA or simulator work."""
from __future__ import annotations

import multiprocessing as mp
import math
import time
import traceback
from pathlib import Path


class RunnerProcessError(RuntimeError):
    def __init__(self, message, code="model_error"):
        super().__init__(message)
        self.code = code


def _child(pipe, cancelled, options):
    runner = None
    try:
        from failureforge.simulation import LiberoRunner
        runner = LiberoRunner(**options)
        while True:
            command = pipe.recv()
            if command is None:
                break
            request, directory = command
            try:
                result = runner.run(request, Path(directory), cancelled.is_set)
                pipe.send((True, result))
            except Exception as exc:
                pipe.send((False, {"code": getattr(exc, "code", "model_error"), "message": str(exc), "traceback": traceback.format_exc()}))
                # Rebuild poisoned render/model context after an execution error.
                break
    except BaseException as exc:
        try:
            pipe.send((False, {"code": "load_error", "message": str(exc), "traceback": traceback.format_exc()}))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        if runner is not None and hasattr(runner, "close"):
            runner.close()
        pipe.close()


class ProcessRunner:
    backend = "libero"

    def __init__(self, model_path, qualification_path, renderer="egl", timeout_seconds=300):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Episode timeout must be finite and positive")
        self.options = {"model_path": Path(model_path), "qualification_path": Path(qualification_path), "renderer": renderer}
        self.timeout_seconds = timeout_seconds
        self.context = mp.get_context("spawn")
        self.process = self.pipe = self.cancel_event = None

    def _start(self):
        self.close()
        self.pipe, child_pipe = self.context.Pipe()
        self.cancel_event = self.context.Event()
        self.process = self.context.Process(target=_child, args=(child_pipe, self.cancel_event, self.options), daemon=True)
        self.process.start()
        child_pipe.close()

    def run(self, request, output_dir, cancelled=lambda: False):
        if self.process is None or not self.process.is_alive():
            self._start()
        self.cancel_event.clear()
        try:
            self.pipe.send((request, str(output_dir)))
        except (EOFError, BrokenPipeError, OSError) as exc:
            self.close()
            raise RunnerProcessError("Robot subprocess could not accept the episode", "worker_lost") from exc
        started, cancellation_started = time.monotonic(), None
        while True:
            try:
                if self.pipe.poll(0.1):
                    success, value = self.pipe.recv()
                    if success:
                        return value
                    (Path(output_dir) / "diagnostic.log").write_text(value.get("traceback", ""), encoding="utf-8")
                    self.close()
                    raise RunnerProcessError(value["message"], value["code"])
            except (EOFError, BrokenPipeError, OSError) as exc:
                self.close()
                raise RunnerProcessError("Robot subprocess exited without a result", "worker_lost") from exc
            if cancelled():
                self.cancel_event.set()
                cancellation_started = cancellation_started or time.monotonic()
                if time.monotonic() - cancellation_started > 10:
                    self.close()
                    return {"outcome": "cancelled", "steps": 0, "task_success": False, "elapsed_seconds": time.monotonic() - started, "backend": "libero"}
            if time.monotonic() - started > self.timeout_seconds:
                self.close()
                raise RunnerProcessError("Robot episode exceeded its wall-time limit; process was terminated", "worker_lost")
            if not self.process.is_alive():
                self.close()
                raise RunnerProcessError("Robot subprocess stopped", "worker_lost")

    def close(self):
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=5)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(timeout=5)
            else:
                self.process.join(timeout=5)
            self.process.close()
            self.process = None
        if self.pipe is not None:
            self.pipe.close()
            self.pipe = None
