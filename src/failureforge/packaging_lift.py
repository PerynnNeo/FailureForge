"""Vertical packing-station fixture under a secured parcel and a prescribed head load."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from pydantic import Field, FiniteFloat, model_validator
from scipy.integrate import solve_ivp

from .contracts import Contract, config_hash


class PackagingLift(Contract):
    payload_kg: FiniteFloat = Field(ge=0, le=1.0, strict=True,
        description="Mass secured to the carriage for the entire cycle, in kilograms.")
    head_force_n: FiniteFloat = Field(ge=0, le=5.0, strict=True,
        description="Downward force applied during the one-second hold, in newtons.")


LIFT_ADAPTERS = ("packaging_lift", "packaging_lift_timed_v2")


class TimedPackagingLift(PackagingLift):
    head_force_n: FiniteFloat = Field(ge=0, le=5, strict=True,
        description="Downward force during the prescribed packing-head pulse, in newtons.")
    head_onset_ms: int = Field(ge=0, lt=2000, strict=True,
        description="Time from the start of the lift cycle to head engagement, in whole milliseconds.")
    head_duration_ms: int = Field(gt=0, le=2000, strict=True,
        description="Duration of the head force pulse, in whole milliseconds.")

    @model_validator(mode="after")
    def pulse_fits_cycle(self):
        if self.head_onset_ms + self.head_duration_ms > 2000:
            raise ValueError("The entire head pulse must fit inside the 2000 ms lift cycle")
        return self


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


def _cycle(mass, intervals, method, max_step):
    state = (0.0, 0.0)
    phases = []
    for start, stop, force in intervals:
        phase = _phase(mass, force, start, stop, state, method, max_step)
        phases.append(phase)
        state = phase.y[:, -1]
    return phases


def _sample(phases, times):
    pieces = []
    for index, phase in enumerate(phases):
        upper = times <= phase.t[-1] if index == len(phases) - 1 else times < phase.t[-1]
        pieces.append(phase.sol(times[(times >= phase.t[0]) & upper]))
    return np.column_stack(pieces)


def _saturated_start(mass, intervals, check_time):
    """Independent piecewise analytic trajectory through the first 20 ms."""
    z, v = 0.0, 0.0
    saturated = True
    for start, end, force in intervals:
        duration = min(end, check_time) - start
        if duration <= 0:
            break
        acceleration = (FIXTURE.force_limit_n - force) / mass - FIXTURE.gravity_m_s2
        z += v * duration + 0.5 * acceleration * duration**2
        v += acceleration * duration
        # For this positive acceleration and upward motion the PD demand
        # decreases throughout the interval; its smallest value is at the end.
        saturated &= acceleration >= 0 and FIXTURE.command(z, v) >= FIXTURE.force_limit_n
    return z, saturated


def _extrema(phase, component):
    times = np.r_[phase.t[0], phase.t_events[component], phase.t[-1]]
    return phase.sol(times)[component]


def run_packaging_lift(inputs: PackagingLift) -> dict:
    f = FIXTURE
    mass = f.empty_mass_kg + inputs.payload_kg
    timed = isinstance(inputs, TimedPackagingLift)
    if timed:
        onset = inputs.head_onset_ms / 1000
        end = (inputs.head_onset_ms + inputs.head_duration_ms) / 1000
        boundaries = sorted({0.0, onset, end, f.arrival_deadline_s, f.end_time_s})
        ticks = np.union1d(np.arange(0, 2001, 10), [inputs.head_onset_ms, inputs.head_onset_ms + inputs.head_duration_ms])
        times = ticks / 1000
    else:
        onset, end = f.arrival_deadline_s, f.end_time_s
        boundaries = [0.0, onset, end]
        # Preserve v1 display times and its inclusive final force sample.
        times = np.r_[np.linspace(0.0, onset, 101)[:-1], np.linspace(onset, end, 101)]
    intervals = [(a, b, inputs.head_force_n if onset <= a < end else 0.0)
                 for a, b in zip(boundaries, boundaries[1:])]
    phases = _cycle(mass, intervals, "DOP853", 0.015625)
    check = _cycle(mass, intervals, "RK45", 0.0078125)
    states = _sample(phases, times)
    other_states = _sample(check, times)
    z, v = states
    motor = np.clip(f.command(z, v), -f.force_limit_n, f.force_limit_n)

    hold_start = boundaries.index(f.arrival_deadline_s)
    hold_positions = np.concatenate([_extrema(phase, 0) for phase in phases[hold_start:]])
    check_hold = np.concatenate([_extrema(phase, 0) for phase in check[hold_start:]])
    positions = np.concatenate([_extrema(phase, 0) for phase in phases])
    velocities = np.concatenate([_extrema(phase, 1) for phase in phases])
    arrival_error = float(abs(f.target_m - phases[hold_start - 1].y[0, -1]))
    max_hold_error = float(np.max(np.abs(hold_positions - f.target_m)))
    check_max_hold_error = float(np.max(np.abs(check_hold - f.target_m)))
    position_difference, velocity_difference = np.max(np.abs(states - other_states), axis=1)
    check_time = 0.02
    analytic_z, saturated = _saturated_start(mass, intervals, check_time)
    initial_phase = next(phase for phase in phases if phase.t[-1] >= check_time)
    initial_test_error = float(abs(initial_phase.sol(check_time)[0] - analytic_z))
    convergence_error = max(float(position_difference), abs(max_hold_error - check_max_hold_error))
    diagnostics = {
        "primary_integrator": "DOP853", "comparison_integrator": "RK45",
        "max_position_difference_m": float(position_difference),
        "max_velocity_difference_m_s": float(velocity_difference),
        "hold_peak_difference_m": abs(max_hold_error - check_max_hold_error),
        "initial_constant_acceleration_error_m": initial_test_error,
        "passed": bool(saturated and
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
    if timed:
        fixture.update(name="Packaging lift timed pulse v2",
                       assumptions="Rigidly secured payload on a frictionless vertical guide. One prescribed downward "
                                   "head-force pulse acts from onset up to release. No package deformation or contact geometry.")
    applied = (times >= onset) & ((times < end) if timed else (times <= end))
    result = {"passed": all(criteria.values()) if diagnostics["passed"] else None,
            "fixture": fixture, "fixture_sha256": config_hash(fixture), "criteria": criteria,
            "summary": {"payload_kg": inputs.payload_kg, "head_force_n": inputs.head_force_n,
                        "arrival_error_m": arrival_error, "max_hold_error_m": max_hold_error,
                        "end_error_m": float(abs(f.target_m - z[-1])), "error_limit_m": f.error_limit_m,
                        "peak_actuator_force_n": float(np.max(np.abs(motor))),
                        "peak_speed_m_s": float(np.max(np.abs(velocities)))},
            "series": {"time_s": times.tolist(), "position_m": z.tolist(), "velocity_m_s": v.tolist(),
                       "actuator_force_n": motor.tolist(),
                       "applied_head_force_n": np.where(applied, inputs.head_force_n, 0.0).tolist()},
            "numerical_diagnostics": diagnostics}
    if timed:
        result["summary"].update(head_onset_ms=inputs.head_onset_ms, head_duration_ms=inputs.head_duration_ms)
        edges = []
        for edge in (onset, end):
            index = boundaries.index(edge)
            edges.append({"time_s": edge, "force_before_n": intervals[index - 1][2] if index else 0.0,
                          "force_after_n": intervals[index][2] if index < len(intervals) else 0.0})
        result["force_schedule"] = {
            "contract": "packaging_lift_timed_v2", "channel": "downward_head_force",
            "requested": {"head_force_n": inputs.head_force_n, "head_onset_ms": inputs.head_onset_ms,
                          "head_duration_ms": inputs.head_duration_ms},
            "interval_semantics": "[start,end); time zero is lift start; terminal sample is after release",
            "force_edges": edges,
            "integrated_intervals": [{"start_s": float(phase.t[0]), "end_s": float(phase.t[-1]), "force_n": force}
                                     for phase, (_, _, force) in zip(phases, intervals)],
            "arrival_check_s": f.arrival_deadline_s, "hold_window_s": [f.arrival_deadline_s, f.end_time_s],
        }
    return result
