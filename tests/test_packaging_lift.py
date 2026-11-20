import math

import numpy as np
import pytest
from pydantic import ValidationError

from failureforge.packaging_lift import FIXTURE, PackagingLift
from failureforge.project_bindings import resolve_bindings
from failureforge.project_runs import ProjectTest
from failureforge.project_solver import adapters, run_job, runtime_identity
from failureforge.project_camera_motion import motion_scene
from failureforge.hardware_trials import acceptance_metrics, run_settings
from failureforge.packaging_lift import TimedPackagingLift


def lift(payload, head_force):
    return run_job({"analysis_type": "robot_behavior", "adapter": "packaging_lift",
                    "inputs": {"payload_kg": payload, "head_force_n": head_force}, "assets": {}})


@pytest.mark.parametrize("payload,head", [(0, 0), (0.25, 2), (0.5, 1), (1.0, 5.0)])
def test_fixed_lift_matches_analytic_motion_during_saturation_and_hold(payload, head):
    result = lift(payload, head)
    assert result["numerical_diagnostics"]["passed"]
    traces = result["series"]
    times = np.array(traces["time_s"])
    total_mass = 1 + payload
    # Saturated start: F = m * (z'' + g).
    initial = times <= 0.02
    assert np.array(traces["position_m"])[initial] == pytest.approx(
        0.5 * (30 / total_mass - 9.81) * times[initial] ** 2, abs=1e-8)
    assert np.array(traces["actuator_force_n"])[initial] == pytest.approx(30)
    assert np.array_equal(traces["applied_head_force_n"], np.where(times < 1, 0, head))

    # The hold response has an independent analytical solution in these
    # unsaturated cases. Match the entire trace, including entry velocity.
    dwell = times >= 1
    held_force = np.array(traces["actuator_force_n"])[dwell]
    assert np.max(np.abs(held_force)) < FIXTURE.force_limit_n
    t = times[dwell] - 1
    z = np.array(traces["position_m"])[dwell]
    v = np.array(traces["velocity_m_s"])[dwell]
    z_equilibrium = 0.15 - (payload * 9.81 + head) / 500
    alpha = 40 / (2 * total_mass)
    omega = math.sqrt(500 / total_mass - alpha**2)
    a = z[0] - z_equilibrium
    b = (v[0] + alpha * a) / omega
    predicted = z_equilibrium + np.exp(-alpha * t) * (a * np.cos(omega * t) + b * np.sin(omega * t))
    assert z == pytest.approx(predicted, abs=1e-8)
    assert result["summary"]["max_hold_error_m"] >= max(abs(z - 0.15)) - 1e-10


def test_reference_freezes_controller_and_distinguishes_arrival_from_loaded_dwell():
    nominal = lift(0, 0)
    changed = lift(0.5, 2)
    assert nominal["passed"]
    assert changed["criteria"]["arrived_within_tolerance"]
    assert not changed["criteria"]["held_within_tolerance"]
    assert not changed["passed"]
    assert nominal["fixture_sha256"] == changed["fixture_sha256"]
    assert nominal["summary"]["error_limit_m"] == changed["summary"]["error_limit_m"] == 0.010
    assert "packaging_lift.py" in runtime_identity("packaging_lift")["source_sha256"]
    assert any(a["id"] == "packaging_lift" for a in adapters("robot_behavior"))
    assert all(a["id"] != "packaging_lift" for a in adapters("thermal"))


@pytest.mark.parametrize("values", [
    {"payload_kg": -1}, {"payload_kg": 1.0001}, {"head_force_n": 5.001},
    {"head_force_n": float("nan")}, {"payload_kg": True}, {"kp_n_per_m": 250}, {"payload_kg": "0.5"},
])
def test_only_supported_numeric_environment_inputs_are_accepted(values):
    with pytest.raises(ValidationError):
        PackagingLift.model_validate({"payload_kg": 0, "head_force_n": 0, **values})


def test_payload_binding_accepts_grams_in_project_ci_or_single_runs():
    check = ProjectTest(label="Packed crate", adapter="packaging_lift", inputs={"head_force_n": 1},
                        bindings={"payload_kg": "Package mass"})
    project = {"analysis_type": "robot_behavior", "revision": 1, "parameters": [
        {"name": "Package mass", "unit": "g", "value": "250", "source": "measured", "evidence": "Scale record",
         "range_min": None, "range_max": None}]}
    inputs, evidence = resolve_bindings(check, project)
    assert inputs == {"payload_kg": 0.25, "head_force_n": 1}
    assert evidence["payload_kg"]["resolved_unit"] == "kg"


def timed_lift(onset, duration, *, force=2.0):
    return run_job({"analysis_type": "robot_behavior", "adapter": "packaging_lift_timed_v2", "assets": {},
                    "inputs": {"payload_kg": 0.5, "head_force_n": force, "head_onset_ms": onset,
                               "head_duration_ms": duration}})


def test_timed_lift_changes_arrival_verdict_at_equal_impulse():
    nominal, early = timed_lift(1000, 1000), timed_lift(750, 1000)
    for result, arrival_error, hold_error in ((nominal, 9.810021, 13.949148), (early, 13.949086, 13.949183)):
        assert result["numerical_diagnostics"]["passed"]
        assert result["passed"] is False and result["criteria"]["held_within_tolerance"] is False
        assert result["summary"]["arrival_error_m"] * 1000 == pytest.approx(arrival_error, abs=1e-5)
        assert result["summary"]["max_hold_error_m"] * 1000 == pytest.approx(hold_error, abs=1e-5)
        intervals = result["force_schedule"]["integrated_intervals"]
        assert sum((p["end_s"] - p["start_s"]) * p["force_n"] for p in intervals) == pytest.approx(2.0)
        assert result["force_schedule"]["hold_window_s"] == [1.0, 2.0]
    assert nominal["criteria"]["arrived_within_tolerance"] is True
    assert early["criteria"]["arrived_within_tolerance"] is False
    assert nominal["fixture_sha256"] == early["fixture_sha256"]
    assert nominal["fixture_sha256"] != lift(0.5, 2)["fixture_sha256"]
    assert "packaging_lift.py" in runtime_identity("packaging_lift_timed_v2")["source_sha256"]


@pytest.mark.parametrize("onset,duration", [(0, 1), (7, 9), (991, 9), (1000, 1000), (1999, 1)])
def test_between_sample_pulse_edges_are_integrated_and_replayed(onset, duration):
    result = timed_lift(onset, duration)
    series = result["series"]
    assert result["numerical_diagnostics"]["passed"]
    t = np.array(series["time_s"])
    start, end = onset / 1000, (onset + duration) / 1000
    assert start in t and end in t
    assert result["force_schedule"]["force_edges"] == [
        {"time_s": start, "force_before_n": 0, "force_after_n": 2},
        {"time_s": end, "force_before_n": 2, "force_after_n": 0}]
    assert np.array_equal(series["applied_head_force_n"], np.where((t >= start) & (t < end), 2, 0))
    assert result["summary"]["max_hold_error_m"] >= max(abs(np.asarray(series["position_m"])[t >= 1] - .15)) - 1e-10
    scene = motion_scene({"adapter": "packaging_lift_timed_v2", "result": result})
    arrow = next(i for i, obj in enumerate(scene.objects) if obj.kind == "mesh")
    assert scene.frame(start).positions[arrow, 2] > scene.floor_z
    assert scene.frame(end).positions[arrow, 2] < scene.floor_z


@pytest.mark.parametrize("onset,duration", [(-1, 20), (2000, 1), (0, 0), (999, 1002), (1.0, 5), (True, 30)])
def test_invalid_or_fractional_ticks_are_rejected(onset, duration):
    with pytest.raises(ValidationError):
        TimedPackagingLift(payload_kg=0, head_force_n=1, head_onset_ms=onset, head_duration_ms=duration)


def test_timed_trial_requires_alignment_and_timing_bindings_are_whole_ms():
    test = ProjectTest(label="Timed head", adapter="packaging_lift_timed_v2",
                       inputs={"payload_kg": 0.5, "head_force_n": 2.0, "head_duration_ms": 1000},
                       bindings={"head_onset_ms": "Engage at"})
    project = {"revision": 1, "analysis_type": "robot_behavior", "parameters": [
        {"name": "Engage at", "source": "measured", "evidence": "Timestamp", "unit": "s",
         "value": "0.75", "range_min": None, "range_max": None}]}
    inputs, bindings = resolve_bindings(test, project)
    assert inputs["head_onset_ms"] == 750 and bindings["head_onset_ms"]["resolved_unit"] == "ms"
    result = timed_lift(750, 1000)
    run = {"adapter": "packaging_lift_timed_v2", "result": result, "inputs": inputs}
    assert run_settings(run) == inputs
    assert acceptance_metrics(run) == {}
    short_pulse = test.model_copy(update={"inputs": {**test.inputs, "head_duration_ms": 10}})
    project["parameters"][0]["value"] = "1.001"
    assert resolve_bindings(short_pulse, project)[0]["head_onset_ms"] == 1001
    project["parameters"][0]["value"] = "0.7501"
    with pytest.raises(ValueError, match="whole-number millisecond"):
        resolve_bindings(test, project)
