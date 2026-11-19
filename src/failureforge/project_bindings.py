"""Resolve declared scalar inputs against the exact saved project revision."""
from __future__ import annotations

import math
import re

from .project_solver import MODELS


UNIT_FACTORS = {
    "m": {"m": 1, "cm": 1e-2, "mm": 1e-3, "µm": 1e-6, "um": 1e-6},
    "m²": {"m²": 1, "m2": 1, "m^2": 1, "cm²": 1e-4, "cm2": 1e-4, "mm²": 1e-6, "mm2": 1e-6},
    "Pa": {"Pa": 1, "kPa": 1e3, "MPa": 1e6, "GPa": 1e9},
    "N": {"N": 1, "kN": 1e3, "mN": 1e-3},
    "kg": {"kg": 1, "g": 1e-3},
    "N/m": {"N/m": 1, "kN/m": 1e3, "N/mm": 1e3},
    "K": {"K": 1},
    "W/(m·K)": {"W/(m·K)": 1, "W/(m*K)": 1, "W/(m K)": 1, "W/m/K": 1, "mW/(m·K)": 1e-3},
    "W/(m²·K)": {"W/(m²·K)": 1, "W/(m2*K)": 1, "W/m2/K": 1, "kW/(m²·K)": 1e3},
    "W/m³": {"W/m³": 1, "W/m3": 1, "W/m^3": 1, "kW/m³": 1e3, "kW/m3": 1e3, "W/cm³": 1e6},
    "1/s": {"1/s": 1, "s^-1": 1, "s⁻¹": 1},
    "s": {"s": 1, "ms": 1e-3},
    "rad": {"rad": 1, "mrad": 1e-3},
    "1": {"1": 1},
}
FIELD_UNITS = {
    "structural_beam": {"length_m": "m", "width_m": "m", "height_m": "m", "young_modulus_pa": "Pa",
                        "tip_force_n": "N", "distributed_load_n_per_m": "N/m", "face_pressure_pa": "Pa", "elements": "1",
                        "max_surface_stress_pa": "Pa", "max_displacement_m": "m",
                        "convergence_tolerance_m": "m", "stress_convergence_tolerance_pa": "Pa"},
    "thermal_rod": {"length_m": "m", "area_m2": "m²", "conductivity_w_mk": "W/(m·K)",
                    "left_temperature_k": "K", "right_temperature_k": "K", "heat_generation_w_m3": "W/m³",
                    "right_ambient_temperature_k": "K", "right_film_coefficient_w_m2k": "W/(m²·K)",
                    "max_temperature_k": "K", "elements": "1", "convergence_tolerance_k": "K"},
    "robot_motion": {"gain_per_s": "1/s", "time_constant_s": "s", "duration_s": "s", "samples": "1"},
    "packaging_lift": {"payload_kg": "kg", "head_force_n": "N"},
    "joint_response": {"min_time_constant_s": "s", "max_time_constant_s": "s", "max_validation_rmse_rad": "rad"},
}


def binding_units(adapter, analysis_type):
    if adapter == "calibration":
        return {"validation_tolerance": "m" if analysis_type == "structural" else "K"}
    return FIELD_UNITS.get(adapter, {})


def binding_catalog(adapter, analysis_type):
    fields = binding_units(adapter, analysis_type)
    return {"binding_units": fields, "binding_accepted_units": {k: list(UNIT_FACTORS[u]) for k, u in fields.items()}}


def resolve_bindings(test, project):
    inputs = dict(test.inputs)
    evidence = {}
    if not test.bindings:
        return inputs, evidence
    units = binding_units(test.adapter, project["analysis_type"])
    parameters = {p["name"].casefold(): p for p in project["parameters"]}
    for field, name in test.bindings.items():
        if field not in units:
            raise ValueError(f"{field} is not a bindable scalar input for {test.adapter}")
        if field in inputs:
            raise ValueError(f"{field} cannot have both a literal input and a parameter binding")
        parameter = parameters.get(name.casefold())
        if parameter is None:
            raise ValueError(f"Project parameter {name!r} is missing in revision {project['revision']}")
        value_text, unit = parameter["value"], parameter["unit"]
        expected = units[field]
        factor = UNIT_FACTORS[expected].get(unit)
        if factor is None:
            raise ValueError(f"{field} requires units compatible with {expected}; {name!r} declares {unit!r}")
        if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?", value_text):
            raise ValueError(f"Project parameter {name!r} must contain one finite number, with its unit stored separately")
        value = float(value_text)
        resolved = value * factor
        if not math.isfinite(resolved):
            raise ValueError(f"Project parameter {name!r} overflows the supported numeric range")
        lower, upper = parameter["range_min"], parameter["range_max"]
        if lower is not None and not lower <= value <= upper:
            raise ValueError(f"Project parameter {name!r} lies outside its declared range")
        if expected == "1":
            if not resolved.is_integer():
                raise ValueError(f"{field} requires a whole-number count")
            resolved = int(resolved)
        inputs[field] = resolved
        evidence[field] = {"parameter_name": parameter["name"], "source_value": value_text, "source_unit": unit,
                           "resolved_value": resolved, "resolved_unit": expected, "source": parameter["source"],
                           "evidence": parameter["evidence"], "range_min": lower, "range_max": upper}
    # Use the worker's exact model constraints, including cross-field limits.
    raw = dict(inputs)
    if test.adapter in ("structural_beam", "thermal_rod", "calibration"):
        raw.setdefault("kind", test.adapter)
    MODELS[test.adapter].model_validate(raw)
    return inputs, evidence
