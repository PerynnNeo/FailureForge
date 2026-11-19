import math

import numpy as np
import pytest
from pydantic import ValidationError

from failureforge.packaging_lift import FIXTURE, PackagingLift
from failureforge.project_bindings import resolve_bindings
from failureforge.project_runs import ProjectTest
from failureforge.project_solver import adapters, run_job, runtime_identity


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
