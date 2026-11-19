from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import math
import threading
import time
from typing import Any
import uuid

import numpy as np

from failureforge.contracts import ERROR_OUTCOMES, VALID_OUTCOMES
from failureforge.persistence import LeaseLost
from failureforge.search import ReductionPlanner, SearchPlanner, preserves_witness, select_witness
from failureforge.search.planner import REFERENCE, SEARCH_VERSION, ZERO_TOLERANCE
from failureforge.search.reduction import REDUCTION_VERSION

FAILURE_OUTCOMES = VALID_OUTCOMES - {"success"}


class JobCancelled(RuntimeError):
    pass


class JobExecutionError(RuntimeError):
    pass


class Worker:
    """Run one episode at a time; all GPU ownership stays in the supplied runner.

    The synthetic backend must be explicitly selected by the caller. This class
    never falls back from a failing robot runtime to diagnostic executions.
    """

    def __init__(self, store: Any, artifact_store: Any, runner: Any, backend: str = "synthetic", worker_id: str | None = None):
        if backend not in {"synthetic", "libero"}:
            raise ValueError("Worker backend must be synthetic or libero")
        runner_backend = getattr(runner, "backend", backend)
        if runner_backend != backend:
            raise ValueError("Worker backend does not match its runner")
        self.store, self.artifacts, self.runner = store, artifact_store, runner
        self.backend = backend
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        self.last_error: str | None = None
        self.last_job_id: str | None = None
        self._job: dict[str, Any] = {}
        self._spec: dict[str, Any] = {}
        self._lease_error: BaseException | None = None
        self._cancelled = threading.Event()

    @property
    def _fence(self) -> tuple[str, str]:
        return self._job["id"], self._job["lease_token"]

    def run_once(self, target_job_id: str | None = None) -> bool:
        self.last_error = None
        self.store.worker_heartbeat(self.worker_id, self.backend)
        job = self.store.claim_job(self.backend, self.worker_id, lease_seconds=60, target_job_id=target_job_id)
        if job is None:
            return False
        self._job = dict(job)
        self.last_job_id = job["id"]
        self._spec = self.store.get_campaign(job["campaign_id"])["spec"]
        self._lease_error = None
        self._cancelled.clear()
        try:
            with self._renew_lease():
                self._check_cancel()
                handler = {"search": self._search, "reduce": self._reduce, "confirm": self._confirm, "rerun": self._rerun}.get(job["kind"])
                if handler is None:
                    raise JobExecutionError(f"Unsupported job kind: {job['kind']}")
                handler()
                self._check_cancel()
                self.store.finish_job(*self._fence, "succeeded")
        except JobCancelled as exc:
            self.last_error = str(exc)
            self._finish_safely("cancelled", self.last_error)
        except LeaseLost as exc:
            self.last_error = str(exc)
            # The replacement worker owns completion and recovery from here.
            self._lease_error = exc
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._finish_safely("failed", self.last_error)
        return True

    def _finish_safely(self, status: str, error: str) -> None:
        try:
            self.store.finish_job(*self._fence, status, error=error)
        except LeaseLost:
            pass
        except Exception:
            # A lost lease intentionally prevents the old worker changing state.
            # The claiming worker or reconciliation owns that job now.
            if self._lease_error is None:
                raise

    @contextmanager
    def _renew_lease(self):
        finished = threading.Event()

        def renew() -> None:
            while not finished.wait(10):
                try:
                    self.store.heartbeat(*self._fence)
                    self.store.worker_heartbeat(self.worker_id, self.backend)
                    if self.store.cancel_requested(*self._fence):
                        self._cancelled.set()
                except BaseException as exc:
                    self._lease_error = exc
                    self._cancelled.set()
                    return

        self.store.heartbeat(*self._fence)
        thread = threading.Thread(target=renew, name=f"lease-{self.worker_id}", daemon=True)
        thread.start()
        try:
            yield
        finally:
            finished.set()
            thread.join(timeout=1)

    def _check_cancel(self) -> None:
        if self._lease_error is not None:
            raise JobExecutionError(f"Worker lease was lost: {self._lease_error}")
        if self._cancelled.is_set() or self.store.cancel_requested(*self._fence):
            raise JobCancelled("Cancellation requested; no further episodes will start")

    def _seed(self, state_id: int) -> int:
        return int(np.random.SeedSequence([self._spec["seed"], int(state_id), 41]).generate_state(1)[0] % (2**31 - 1))

    def _episodes(self, phase: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_episodes(self._job["campaign_id"], phase=phase)

    @staticmethod
    def _outcome(episode: Mapping[str, Any]) -> str:
        return str(episode.get("outcome") or (episode.get("result") or {}).get("outcome", ""))

    def _episode(self, phase: str, stage: str, state_id: int, scene: Mapping[str, float], condition: str,
                 candidate_id: str | None = None) -> dict[str, Any]:
        request_key = f"{self._job['id']}:{phase}:{stage}:{state_id}:{condition}"
        request = {"state_id": state_id, "seed": self._seed(state_id), "scene_change": dict(scene),
                   "max_steps": 280, "control_hz": 20, "condition": condition, "phase": phase,
                   "stage": stage, "request_key": request_key, "backend": self.backend}
        if candidate_id is not None:
            request["candidate_id"] = candidate_id
        for saved in self._episodes(phase):
            saved_request = saved.get("request", saved)
            if saved_request.get("request_key") != request_key:
                continue
            saved_specification = {key: value for key, value in saved_request.items() if key != "_retry"}
            if saved_specification != request:
                raise JobExecutionError("The requested episode differs from its persisted specification; resume cannot change experiment settings")
            if saved["status"] == "completed" and self._outcome(saved) in VALID_OUTCOMES:
                self.artifacts.verify_episode(saved["artifact_manifest"])
                return saved

        while True:
            self._check_cancel()
            episode_id = self.store.reserve_episode(*self._fence, phase, request)
            try:
                directory = self.artifacts.begin_episode(episode_id, self._job["lease_token"])
            except Exception as exc:
                self._record_failure(episode_id, "artifact_error", exc)
                continue
            last_poll = 0.0

            def cancelled() -> bool:
                nonlocal last_poll
                if self._cancelled.is_set():
                    return True
                if time.monotonic() - last_poll >= 0.25:
                    last_poll = time.monotonic()
                    try:
                        if self.store.cancel_requested(*self._fence):
                            self._cancelled.set()
                    except BaseException as exc:
                        self._lease_error = exc
                        self._cancelled.set()
                return self._cancelled.is_set()

            try:
                result = self.runner.run(request, directory, cancelled)
            except Exception as exc:
                code = getattr(exc, "code", "model_error")
                code = code if code in ERROR_OUTCOMES | {"invalid_scene"} else "model_error"
                self._record_failure(episode_id, code, exc)
                continue
            if not isinstance(result, Mapping):
                self._record_failure(episode_id, "numerical_error", JobExecutionError("Runner did not produce an outcome record"))
                continue
            if result.get("outcome") == "cancelled":
                self.store.fail_episode(*self._fence, episode_id, "cancelled", "Cancelled during episode execution")
                raise JobCancelled("Cancelled during episode execution")
            if result.get("outcome") in ERROR_OUTCOMES | {"invalid_scene"}:
                self._record_failure(episode_id, result["outcome"], JobExecutionError(str(result.get("error", result["outcome"]))))
                continue
            try:
                valid = (result.get("outcome") in VALID_OUTCOMES and result.get("backend") == self.backend and
                         bool(result.get("task_success")) == (result.get("outcome") == "success") and
                         isinstance(result.get("steps"), int) and not isinstance(result.get("steps"), bool) and
                         0 <= result["steps"] <= 280 and math.isfinite(float(result.get("elapsed_seconds", -1))) and
                         float(result.get("elapsed_seconds", -1)) >= 0)
            except (ValueError, TypeError):
                valid = False
            if not valid:
                self._record_failure(episode_id, "numerical_error", JobExecutionError("Runner produced an invalid outcome record"))
                continue
            if self._lease_error is not None:
                self._check_cancel()
            try:
                manifest = self.artifacts.publish_episode(episode_id, self._job["lease_token"], directory, result)
            except Exception as exc:
                self._record_failure(episode_id, "artifact_error", exc)
                continue
            # Publication alone cannot expose an episode. The fenced commit does.
            self.store.complete_episode(*self._fence, episode_id, result, manifest)
            return {"id": episode_id, "status": "completed", "request": request, "result": result, **request, **result}

    def _record_failure(self, episode_id: str, outcome: str, error: Exception) -> None:
        self.store.fail_episode(*self._fence, episode_id, outcome, f"{type(error).__name__}: {error}")
        if outcome == "invalid_scene":
            raise JobExecutionError(f"A declared scene was rejected as invalid: {error}")
        failures = sum(self._outcome(row) in ERROR_OUTCOMES for row in self._episodes())
        if failures > 2:
            raise JobExecutionError(f"Campaign infrastructure retry allowance exhausted after {outcome}: {error}")
        self._check_cancel()

    def _pairs(self, phase: str, stage: str, scene: Mapping[str, float], state_ids: list[int]) -> list[dict[str, Any]]:
        pairs = []
        for state in state_ids:
            reference = self._episode(phase, stage, state, REFERENCE, "reference")
            changed = self._episode(phase, stage, state, scene, "changed")
            pairs.append({"state_id": state, "reference_episode_id": reference["id"], "changed_episode_id": changed["id"],
                          "reference_outcome": self._outcome(reference), "changed_outcome": self._outcome(changed)})
        return pairs

    @staticmethod
    def _ids(pairs: list[dict[str, Any]]) -> list[str]:
        return [pair[key] for pair in pairs for key in ("reference_episode_id", "changed_episode_id")]

    def _search(self) -> None:
        states = self._spec["state_ids"]
        references = [self._episode("baseline", "screening", state, REFERENCE, "reference") for state in states]
        if any(self._outcome(row) != "success" for row in references):
            raise JobExecutionError("Reference screening did not succeed on both search states. Search was not started.")
        planner = SearchPlanner(self._spec["method"], self._spec["seed"], self._spec["domain"])
        for index in range(self._spec["candidate_count"]):
            history = self.store.list_candidates(self._job["campaign_id"])
            scene, reason = planner.propose(index, history)
            candidate_id = self.store.add_candidate(*self._fence, index, scene, reason)
            episodes = [self._episode("search", f"candidate-{index}", state, scene, "changed", candidate_id) for state in states]
            failures = sum(self._outcome(row) in FAILURE_OUTCOMES for row in episodes)
            self.store.complete_candidate(*self._fence, candidate_id, [row["id"] for row in episodes], failures / len(states))
        witness = select_witness(self.store.list_candidates(self._job["campaign_id"]), self._spec["domain"])
        if witness is None:
            return
        all_episodes = {row["id"]: row for row in self._episodes("search")}
        changed = [all_episodes[identifier] for identifier in witness["episode_ids"]]
        changed_by_state = {row.get("state_id", row["request"]["state_id"]): row for row in changed}
        pairs = [{"state_id": state, "reference_episode_id": reference["id"], "changed_episode_id": changed_by_state[state]["id"],
                  "reference_outcome": self._outcome(reference), "changed_outcome": self._outcome(changed_by_state[state])}
                 for state, reference in zip(states, references)]
        self.store.save_case(*self._fence, {
            "campaign_id": self._job["campaign_id"], "candidate_id": witness["id"],
            "backend": self.backend, "evidence_kind": "synthetic_diagnostic" if self.backend == "synthetic" else "robot_simulation",
            "status": "observed", "scene_change": witness["scene_change"], "original_scene_change": witness["scene_change"],
            "failure_state_ids": [pair["state_id"] for pair in pairs if pair["changed_outcome"] in FAILURE_OUTCOMES],
            "pairs": pairs, "episode_ids": self._ids(pairs), "search_pairs": pairs,
            "selection_rule": "max-failures_then-active-parameters_then-directional-linf_then-index-v1",
            "search_version": SEARCH_VERSION, "reduction_history": [], "confirmation_summary": None,
            "search_protocol": {"sobol_pool_size": 32, "warmup_count": min(16, self._spec["candidate_count"]),
                "local_probability": 0.5, "local_unit_square_sigma": 0.10, "rejection_limit": 64,
                "parent_selection": "uniform among completed failing candidates", "out_of_bounds": "reject",
                "canonical_decimal_places": 12, "zero_tolerance": ZERO_TOLERANCE,
                "policy_seed_schedule": "SeedSequence([campaign_seed,state_id,41]).generate_state(1)[0] % (2**31-1)"},
        })

    def _case(self) -> dict[str, Any]:
        case_id = self._job.get("case_id") or self._job.get("payload", {}).get("case_id")
        if not case_id:
            raise JobExecutionError("This job requires a case")
        return self.store.get_case(case_id)

    def _reduce(self) -> None:
        case = self._case()
        case_id = case["id"]
        original = case.get("original_scene_change", case["scene_change"])
        failure_states = case["failure_state_ids"]
        states = self._spec["state_ids"]
        planner = ReductionPlanner(original, self._spec["domain"])
        proposals = case.get("reduction_proposals")
        if proposals is None:
            proposals = planner.proposals()
            self.store.update_case(*self._fence, case_id, {"reduction_proposals": proposals, "reduction_version": REDUCTION_VERSION})
        initial = self._pairs("reduction", "initial-verification", original, states)
        all_ids = list(dict.fromkeys(case["episode_ids"] + self._ids(initial)))
        stable = all(pair["reference_outcome"] == "success" for pair in initial) and preserves_witness(
            {pair["state_id"]: pair["changed_outcome"] for pair in initial}, failure_states)
        self.store.update_case(*self._fence, case_id, {"reduction_version": REDUCTION_VERSION,
            "reduction_initial_pairs": initial, "episode_ids": all_ids,
            "status": "reducing" if stable else "unstable"})
        if not stable:
            return
        incumbent = original
        history = []
        for proposal in proposals:
            episodes = [self._episode("reduction", f"proposal-{proposal['index']}", state, proposal["scene_change"], "changed") for state in states]
            outcomes = {state: self._outcome(row) for state, row in zip(states, episodes)}
            preserved = preserves_witness(outcomes, failure_states)
            accepted = preserved and planner.is_improvement(proposal["scene_change"], incumbent)
            if accepted:
                incumbent = proposal["scene_change"]
            entry = {**proposal, "outcomes": {str(key): value for key, value in outcomes.items()},
                     "preserves_witness": preserved, "accepted": accepted, "episode_ids": [row["id"] for row in episodes]}
            history.append(entry)
            all_ids = list(dict.fromkeys(all_ids + entry["episode_ids"]))
            self.store.update_case(*self._fence, case_id, {"reduction_history": history, "episode_ids": all_ids})
        final_pairs = self._pairs("reduction", "final-verification", incumbent, states)
        reproduced = all(pair["reference_outcome"] == "success" for pair in final_pairs) and preserves_witness(
            {pair["state_id"]: pair["changed_outcome"] for pair in final_pairs}, failure_states)
        self.store.update_case(*self._fence, case_id, {
            "scene_change": incumbent, "pairs": final_pairs, "reduction_final_pairs": final_pairs,
            "episode_ids": list(dict.fromkeys(all_ids + self._ids(final_pairs))),
            "status": "reproduced" if reproduced else "unstable",
            "reduced": planner.is_improvement(incumbent, original),
            "reduction_claim": "Smallest retained witness among evaluated proposals; no global minimum established.",
        })

    def _confirm(self) -> None:
        case = self._case()
        frozen_scene = case.get("confirmation_frozen_scene_change")
        if frozen_scene is None:
            frozen_scene = dict(case["scene_change"])
            self.store.update_case(*self._fence, case["id"], {"confirmation_frozen_scene_change": frozen_scene})
        pairs = self._pairs("confirmation", "held-out", frozen_scene, self._spec["confirmation_state_ids"])
        counts = {"both_success": 0, "induced_failure": 0, "both_failure": 0, "changed_only_success": 0}
        for pair in pairs:
            reference_ok = pair["reference_outcome"] == "success"
            changed_ok = pair["changed_outcome"] == "success"
            category = ("both_success" if changed_ok else "induced_failure") if reference_ok else ("changed_only_success" if changed_ok else "both_failure")
            pair["category"] = category
            counts[category] += 1
        denominator = len(pairs)
        summary = {**counts, "denominator": denominator,
                   "reference_successes": counts["both_success"] + counts["induced_failure"],
                   "changed_successes": counts["both_success"] + counts["changed_only_success"],
                   "induced_failure_denominator": counts["both_success"] + counts["induced_failure"],
                   "frozen_scene_change": frozen_scene,
                   "claim": "Paired outcomes on the declared held-out state bank; no population estimate."}
        self.store.update_case(*self._fence, case["id"], {"confirmation_summary": summary,
            "confirmation_pairs": pairs, "confirmation_status": "completed",
            "episode_ids": list(dict.fromkeys(case["episode_ids"] + self._ids(pairs)))})

    def _rerun(self) -> None:
        case = self._case()
        state = int(case["failure_state_ids"][0])
        pairs = self._pairs("rerun", "fresh-inference", case["scene_change"], [state])
        pair = pairs[0]
        reruns = list(case.get("reruns", []))
        # Each explicit job is a new execution. Recovery of that job is idempotent.
        reruns = [item for item in reruns if item["job_id"] != self._job["id"]]
        reruns.append({"job_id": self._job["id"], "pairs": pairs,
            "scene_change": dict(case["scene_change"]),
            "reproduced": pair["reference_outcome"] == "success" and pair["changed_outcome"] in FAILURE_OUTCOMES})
        self.store.update_case(*self._fence, case["id"], {"reruns": reruns,
            "episode_ids": list(dict.fromkeys(case["episode_ids"] + self._ids(pairs)))})
