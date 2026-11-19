"""Vertical packing-station fixture under a secured parcel and a prescribed head load."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from pydantic import Field, FiniteFloat
from scipy.integrate import solve_ivp

from .contracts import Contract, config_hash


class PackagingLift(Contract):
    payload_kg: FiniteFloat = Field(ge=0, le=1.0, strict=True,
        description="Mass secured to the carriage for the entire cycle, in kilograms.")
    head_force_n: FiniteFloat = Field(ge=0, le=5.0, strict=True,
        description="Downward force applied during the one-second hold, in newtons.")


@dataclass(frozen=True)
class LiftFixture:
    # Mass, travel, rated speed and force are from configs/vertical-slide.urdf.
    empty_mass_kg: float = 1.0
    gravity_m_s2: float = 9.81
    lower_travel_m: float = -0.5
    upper_travel_m: float = 0.5
    speed_limit_m_s: float = 2.0
    force_limit_n: float = 30.0
    kp_n_per_m: float = 500.0
    kd_n_s_per_m: float = 40.0
    target_m: float = 0.15
    arrival_deadline_s: float = 1.0
    end_time_s: float = 2.0
    error_limit_m: float = 0.010

    def command(self, z, v):
        # Fixed feedforward compensates gravity on the empty carriage.
        return self.empty_mass_kg * self.gravity_m_s2 + self.kp_n_per_m * (self.target_m - z) - self.kd_n_s_per_m * v


FIXTURE = LiftFixture()


def _phase(mass, head_force, start, stop, initial, method, max_step):
    def acceleration(z, v):
        force = min(FIXTURE.force_limit_n, max(-FIXTURE.force_limit_n, FIXTURE.command(z, v)))
        return (force - head_force) / mass - FIXTURE.gravity_m_s2

    def derivative(time, state):
        z, v = state
        return (v, acceleration(z, v))

    # Position and speed extrema occur at phase endpoints or zeros of v and a.
    # Evaluate them independently of the coarse display trace.
    def position_extremum(time, state):
        return state[1]

    def velocity_extremum(time, state):
        return acceleration(*state)

    result = solve_ivp(derivative, (start, stop), initial, method=method, dense_output=True,
                       events=(position_extremum, velocity_extremum), max_step=max_step,
                       rtol=1e-9, atol=1e-11)
    if not result.success or not np.isfinite(result.y).all():
        raise RuntimeError("Lift integration did not finish with finite states")
    return result


def _cycle(mass, force, method, max_step):
    f = FIXTURE
    rise = _phase(mass, 0.0, 0, f.arrival_deadline_s, (0.0, 0.0), method, max_step)
    hold = _phase(mass, force, f.arrival_deadline_s, f.end_time_s, rise.y[:, -1], method, max_step)
    return rise, hold


def _extrema(phase, component):
    times = np.r_[phase.t[0], phase.t_events[component], phase.t[-1]]
    return phase.sol(times)[component]


def run_packaging_lift(inputs: PackagingLift) -> dict:
    f = FIXTURE
    mass = f.empty_mass_kg + inputs.payload_kg
    rise, hold = _cycle(mass, inputs.head_force_n, "DOP853", 0.015625)
    check_rise, check_hold = _cycle(mass, inputs.head_force_n, "RK45", 0.0078125)
    rise_display = np.linspace(0.0, f.arrival_deadline_s, 101)
    hold_display = np.linspace(f.arrival_deadline_s, f.end_time_s, 101)
    times = np.r_[rise_display[:-1], hold_display]
    states = np.column_stack((rise.sol(rise_display[:-1]), hold.sol(hold_display)))
    other_states = np.column_stack((check_rise.sol(rise_display[:-1]), check_hold.sol(hold_display)))
    z, v = states
    motor = np.clip(f.command(z, v), -f.force_limit_n, f.force_limit_n)

    hold_positions = _extrema(hold, 0)
    positions = np.r_[_extrema(rise, 0), hold_positions]
    velocities = np.r_[_extrema(rise, 1), _extrema(hold, 1)]
    arrival_error = float(abs(f.target_m - rise.y[0, -1]))
    max_hold_error = float(np.max(np.abs(hold_positions - f.target_m)))
    check_max_hold_error = float(np.max(np.abs(_extrema(check_hold, 0) - f.target_m)))
    position_difference, velocity_difference = np.max(np.abs(states - other_states), axis=1)
    # The motor is positively saturated through the first 20 ms throughout the
    # supported mass range. The rise from rest in that interval has constant acceleration.
    check_time = 0.02
    initial_acceleration = f.force_limit_n / mass - f.gravity_m_s2
    analytic_z = 0.5 * initial_acceleration * check_time**2
    analytic_v = initial_acceleration * check_time
    initial_test_error = float(abs(rise.sol(check_time)[0] - analytic_z))
    convergence_error = max(float(position_difference), abs(max_hold_error - check_max_hold_error))
    diagnostics = {
        "primary_integrator": "DOP853", "comparison_integrator": "RK45",
        "max_position_difference_m": float(position_difference),
        "max_velocity_difference_m_s": float(velocity_difference),
        "hold_peak_difference_m": abs(max_hold_error - check_max_hold_error),
        "initial_constant_acceleration_error_m": initial_test_error,
        "passed": bool(f.command(analytic_z, analytic_v) >= f.force_limit_n and
                       initial_test_error <= 1e-8 and convergence_error <= 1e-7 and velocity_difference <= 1e-5),
    }
    criteria = {
        "arrived_within_tolerance": arrival_error <= f.error_limit_m,
        "held_within_tolerance": max_hold_error <= f.error_limit_m,
        "stayed_within_travel": bool(positions.min() >= f.lower_travel_m and positions.max() <= f.upper_travel_m),
        "stayed_within_speed_limit": bool(np.max(np.abs(velocities)) <= f.speed_limit_m_s),
    }
    # Reaching a travel stop requires contact dynamics outside this ideal guide.
    if not criteria["stayed_within_travel"]:
        diagnostics["passed"] = False
        diagnostics["reason"] = "The fixture reached a mechanical travel stop outside the free-motion model"
    fixture = {"name": "Packaging lift v1", **asdict(f), "initial_height_m": 0.0, "initial_speed_m_s": 0.0,
               "controller": "Force-limited PD with fixed empty-carriage gravity compensation",
               "assumptions": "Rigidly secured payload on a frictionless vertical guide. A timed downward force "
                              "represents the head during the hold. No package deformation or head contact geometry."}
    return {"passed": all(criteria.values()) if diagnostics["passed"] else None,
            "fixture": fixture, "fixture_sha256": config_hash(fixture), "criteria": criteria,
            "summary": {"payload_kg": inputs.payload_kg, "head_force_n": inputs.head_force_n,
                        "arrival_error_m": arrival_error, "max_hold_error_m": max_hold_error,
                        "end_error_m": float(abs(f.target_m - z[-1])), "error_limit_m": f.error_limit_m,
                        "peak_actuator_force_n": float(np.max(np.abs(motor))),
                        "peak_speed_m_s": float(np.max(np.abs(velocities)))},
            "series": {"time_s": times.tolist(), "position_m": z.tolist(), "velocity_m_s": v.tolist(),
                       "actuator_force_n": motor.tolist(),
                       "applied_head_force_n": np.where(times >= f.arrival_deadline_s, inputs.head_force_n, 0.0).tolist()},
            "numerical_diagnostics": diagnostics}
