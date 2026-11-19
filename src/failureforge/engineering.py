"""Bounded, one-dimensional SI engineering studies and scalar parameter fitting."""
from __future__ import annotations

from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


Length = Annotated[float, Field(ge=1e-6, le=1e4)]
Positive = Annotated[float, Field(gt=0)]
Force = Annotated[float, Field(ge=-1e12, le=1e12)]
Temperature = Annotated[float, Field(gt=0, le=1e5)]
Generation = Annotated[float, Field(ge=0, le=1e12)]


class StudyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True, str_strip_whitespace=True)


class BeamStudy(StudyInput):
    kind: Literal["structural_beam"]
    length_m: Length
    width_m: Length
    height_m: Length
    young_modulus_pa: float = Field(ge=1, le=1e13)
    tip_force_n: Force = 0
    distributed_load_n_per_m: Force = 0
    face_pressure_pa: Force | None = Field(default=None, description="Uniform signed pressure normal to the full span × width face. Positive pressure bends in the positive tip-force direction.")
    elements: int = Field(default=16, ge=2, le=128)
    max_surface_stress_pa: Positive | None = None
    max_displacement_m: Positive | None = None
    convergence_tolerance_m: Positive | None = None
    stress_convergence_tolerance_pa: Positive | None = None

    @model_validator(mode="after")
    def slender(self):
        if self.length_m < 10 * self.height_m:
            raise ValueError("Euler-Bernoulli bending requires length at least ten times the bending depth")
        return self

    @property
    def transverse_load_n_per_m(self):
        return self.distributed_load_n_per_m + (self.face_pressure_pa or 0.0) * self.width_m

    def recorded_inputs(self):
        return self.model_dump(exclude={"face_pressure_pa"} if self.face_pressure_pa is None else set())


class ThermalStudy(StudyInput):
    kind: Literal["thermal_rod"]
    length_m: Length
    area_m2: float = Field(ge=1e-12, le=1e6)
    conductivity_w_mk: float = Field(ge=1e-6, le=1e6)
    left_temperature_k: Temperature
    right_temperature_k: Temperature | None = Field(default=None, description="Prescribed right surface temperature. Leave blank when using the ambient and film coefficient instead.")
    right_ambient_temperature_k: Temperature | None = Field(default=None, description="Fluid temperature outside the right end face. Use with the right film coefficient and leave the right surface temperature blank.")
    right_film_coefficient_w_m2k: float | None = Field(default=None, ge=0, le=1e7, description="Uniform heat transfer coefficient on the right end face. Zero insulates this face; a positive value exchanges heat with the specified ambient.")
    heat_generation_w_m3: Generation = 0
    elements: int = Field(default=16, ge=2, le=128)
    max_temperature_k: Positive | None = None
    convergence_tolerance_k: Positive | None = None

    @model_validator(mode="after")
    def right_boundary(self):
        ambient = self.right_ambient_temperature_k is not None
        film = self.right_film_coefficient_w_m2k is not None
        if ambient != film or (self.right_temperature_k is not None) == ambient:
            raise ValueError("Specify either the right surface temperature or both the right ambient temperature and film coefficient")
        return self

    def recorded_inputs(self):
        inactive = {"right_temperature_k"} if self.right_temperature_k is None else {
            "right_ambient_temperature_k", "right_film_coefficient_w_m2k"}
        return self.model_dump(exclude=inactive)


EngineeringModel = Annotated[BeamStudy | ThermalStudy, Field(discriminator="kind")]


class BeamReading(StudyInput):
    run_id: str = Field(min_length=1, max_length=120)
    tip_force_n: Force
    tip_displacement_m: float = Field(ge=-1e4, le=1e4)


class ThermalReading(StudyInput):
    run_id: str = Field(min_length=1, max_length=120)
    heat_generation_w_m3: Generation
    position_m: Length
    temperature_k: Temperature


Reading = BeamReading | ThermalReading


class CalibrationStudy(StudyInput):
    kind: Literal["calibration"]
    model: EngineeringModel
    parameter_bounds: list[Positive] = Field(min_length=2, max_length=2)
    validation_tolerance: Positive
    fit: list[Reading] = Field(min_length=1, max_length=500)
    validation: list[Reading] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def comparable_measurements(self):
        beam = isinstance(self.model, BeamStudy)
        if not beam and self.model.right_temperature_k is None:
            raise ValueError("Conductivity calibration currently requires two prescribed end temperatures")
        min_value, max_value = (1, 1e13) if beam else (1e-6, 1e6)
        low, high = self.parameter_bounds
        if not min_value <= low < high <= max_value:
            raise ValueError(f"Parameter bounds must increase within [{min_value:g}, {max_value:g}]")
        readings = [*self.fit, *self.validation]
        if len({item.run_id for item in readings}) != len(readings):
            raise ValueError("Every calibration and validation run needs a distinct run ID")
        for item in readings:
            if beam != isinstance(item, BeamReading):
                raise ValueError("Measurement fields must match the engineering model")
            if isinstance(item, ThermalReading) and item.position_m >= self.model.length_m:
                raise ValueError("Place temperature sensors strictly inside the modeled rod")
        return self


class EngineeringRequest(RootModel[Annotated[BeamStudy | ThermalStudy | CalibrationStudy, Field(discriminator="kind")]]):
    pass


def _assemble(dofs, stiffness):
    size = stiffness.shape[0]
    rows = np.repeat(dofs, size, axis=1).ravel()
    columns = np.tile(dofs, (1, size)).ravel()
    values = np.tile(stiffness.ravel(), len(dofs))
    return coo_matrix((values, (rows, columns))).tocsr()


def _beam_solution(model: BeamStudy, n: int):
    # Rotational degrees of freedom are derivatives with respect to x/L.
    # This gives the assembled equations a consistent scale across beam lengths.
    h = 1 / n
    length = model.length_m
    inertia = model.width_m * model.height_m**3 / 12
    rigidity = model.young_modulus_pa * inertia
    stiffness = np.array([
        [12, 6*h, -12, 6*h],
        [6*h, 4*h*h, -6*h, 2*h*h],
        [-12, -6*h, 12, -6*h],
        [6*h, 2*h*h, -6*h, 4*h*h],
    ]) / h**3
    dofs = 2 * np.arange(n)[:, None] + np.arange(4)
    matrix = _assemble(dofs, stiffness)
    force = np.zeros(2 * (n + 1))
    distributed = model.transverse_load_n_per_m * length**4 / rigidity
    element_load = distributed * np.array([h/2, h*h/12, h/2, -h*h/12])
    np.add.at(force, dofs, np.broadcast_to(element_load, dofs.shape))
    force[-2] += model.tip_force_n * length**3 / rigidity
    solution = np.zeros_like(force)
    solution[2:] = spsolve(matrix[2:, 2:], force[2:])
    v = solution[::2]
    slope_scaled = solution[1::2]
    midpoint = (v[:-1] + v[1:]) / 2 + h * (slope_scaled[:-1] - slope_scaled[1:]) / 8
    curvature_left = (6*(v[1:] - v[:-1])/h**2 - (4*slope_scaled[:-1] + 2*slope_scaled[1:])/h) / length**2
    curvature_right = (6*(v[:-1] - v[1:])/h**2 + (2*slope_scaled[:-1] + 4*slope_scaled[1:])/h) / length**2
    reactions = (matrix @ solution - force)[:2] * np.array([rigidity / length**3, rigidity / length**2])
    return v, slope_scaled / length, midpoint, curvature_left, curvature_right, reactions


def _convergence(n, coarse_midpoints, refined_nodes, unit, tolerance):
    difference = float(np.max(np.abs(coarse_midpoints - refined_nodes[1::2])))
    scale = float(np.max(np.abs(refined_nodes)))
    return {"coarse_elements": n, "reported_elements": 2*n,
            "quantity_unit": unit, "at": "coarse element midpoints",
            "max_abs_change": difference, "relative_to_peak": difference / scale if scale else None,
            "absolute_tolerance": tolerance, "passed": difference <= tolerance if tolerance is not None else None}


def _acceptance(result, limits, diagnostics, scope_ok=True):
    checks = [{"quantity": name, "measured": result["summary"][name], "maximum": limit,
               "passed": result["summary"][name] <= limit} for name, limit in limits if limit is not None]
    numerical_ok = all(check["passed"] for check in diagnostics if check["passed"] is not None)
    result["numerical_diagnostics"] = {"checks": diagnostics, "passed": numerical_ok}
    result["acceptance_checks"] = checks
    result["passed"] = all(check["passed"] for check in checks) if checks and numerical_ok and scope_ok else None
    result["summary"]["passed"] = result["passed"]
    return result


def _balance_check(name, residual, scale):
    # Relative force/heat balance with a small floor for near-zero loads.
    tolerance = max(1e-10, abs(scale)*1e-5)
    return {"quantity": name, "residual": float(residual), "absolute_tolerance": tolerance,
            "passed": bool(abs(residual) <= tolerance)}


def _beam_reference_peaks(model):
    """Exact continuous extrema for these two loads; a limit may lie between nodes."""
    length = model.length_m
    force = model.tip_force_n
    uniform = model.transverse_load_n_per_m * length
    inertia = model.width_m * model.height_m**3 / 12
    # v'(x) / x is quadratic in normalized position x/L.
    slope_roots = np.roots([uniform, -3*(uniform+force), 3*uniform+6*force])
    positions = [0., 1., *(float(v.real) for v in slope_roots if abs(v.imag) < 1e-12 and 0 < v.real < 1)]
    z = np.array(positions)
    v = (4*force*(3-z) + uniform*(6-4*z+z*z))*z*z*length**3 / (24*model.young_modulus_pa*inertia)
    # Moment as a function of distance from the free end, including zero-shear extrema.
    arm = [0., 1.]
    if uniform and 0 < -force/uniform < 1:
        arm.append(-force/uniform)
    max_moment = max(abs(length*y*(force+uniform*y/2)) for y in arm)
    return float(np.max(np.abs(v))), max_moment*model.height_m/(2*inertia)


def _solve_beam(model: BeamStudy):
    n = model.elements
    coarse = _beam_solution(model, n)
    v, slope, mid, k_left, k_right, reactions = _beam_solution(model, 2*n)
    stress_scale = model.young_modulus_pa * model.height_m / 2
    max_displacement = float(max(np.max(np.abs(v)), np.max(np.abs(mid))))
    max_stress = float(stress_scale * max(np.max(np.abs(k_left)), np.max(np.abs(k_right))))
    continuous_displacement, continuous_stress = _beam_reference_peaks(model)
    result = {"kind": model.kind, "solver": "euler_bernoulli_hermite_v1", "inputs": model.recorded_inputs(),
            "summary": {"tip_displacement_m": float(v[-1]), "tip_rotation_rad": float(slope[-1]),
                        "max_sampled_abs_displacement_m": max_displacement,
                        "continuous_max_abs_displacement_m": continuous_displacement,
                        "continuous_max_surface_stress_pa": continuous_stress,
                        "max_surface_bending_stress_pa": max_stress,
                        "root_reaction_n": float(reactions[0]), "root_reaction_moment_nm": float(reactions[1]),
                        "within_small_deflection_screen": continuous_displacement <= 0.05 * model.length_m},
            "traces": {"node_position_m": np.linspace(0, model.length_m, 2*n+1).tolist(),
                       "displacement_m": v.tolist(), "rotation_rad": slope.tolist(),
                       "element_left_surface_stress_pa": (stress_scale * k_left).tolist(),
                       "element_right_surface_stress_pa": (stress_scale * k_right).tolist()},
            "convergence": _convergence(n, coarse[2], v, "m", model.convergence_tolerance_m),
            "assumptions": ["Straight, prismatic, rectangular cantilever with a clamped root and no axial load.",
                            "Signed transverse tip force and uniform distributed load act in one bending plane.",
                            "Linear elasticity and small rotations. Deflection above 5% of span flags that approximation.",
                            "Limit checks use continuous closed-form extrema of this fixture; mesh values and their convergence are reported separately.",
                            "Computed surface bending stress requires a separate material allowable for a strength assessment."]}
    if model.face_pressure_pa is not None:
        result["summary"]["pressure_line_load_n_per_m"] = model.face_pressure_pa * model.width_m
        result["summary"]["total_distributed_load_n_per_m"] = model.transverse_load_n_per_m
        result["assumptions"].append("Static face pressure acts uniformly across span and width, adding pressure × width to the signed line load.")
    coarse_peak = stress_scale * max(np.max(np.abs(coarse[3])), np.max(np.abs(coarse[4])))
    stress_change = float(abs(max_stress - coarse_peak))
    stress_tolerance = model.stress_convergence_tolerance_pa
    result["convergence"]["peak_stress"] = {
        "change_pa": stress_change, "absolute_tolerance_pa": stress_tolerance,
        "passed": None if stress_tolerance is None else stress_change <= stress_tolerance}
    force = model.tip_force_n
    distributed = model.transverse_load_n_per_m * model.length_m
    force_residual = reactions[0] + force + distributed
    moment_residual = reactions[1] + model.length_m * (force + distributed / 2)
    checks = [_balance_check("net_force_n", force_residual, abs(force) + abs(distributed)),
              _balance_check("net_moment_nm", moment_residual, model.length_m * (abs(force) + abs(distributed/2))),
              {"quantity": "mesh_displacement", "passed": result["convergence"]["passed"]},
              {"quantity": "mesh_peak_stress", "passed": result["convergence"]["peak_stress"]["passed"]}]
    return _acceptance(result, [("continuous_max_surface_stress_pa", model.max_surface_stress_pa),
                                ("continuous_max_abs_displacement_m", model.max_displacement_m)], checks,
                       result["summary"]["within_small_deflection_screen"])


def _thermal_solution(model: ThermalStudy, n: int, right_surface: float):
    dx = model.length_m / n
    matrix = _assemble(np.arange(n)[:, None] + np.arange(2), np.array([[1., -1.], [-1., 1.]]))
    # Equilibrate the interior equations around the exact imposed linear boundary field.
    boundary_field = np.linspace(model.left_temperature_k, right_surface, n+1)
    source = model.heat_generation_w_m3 * dx**2 / model.conductivity_w_mk
    rise = np.zeros(n+1)
    rise[1:-1] = spsolve(matrix[1:-1, 1:-1], np.full(n-1, source))
    temperature = boundary_field + rise
    flux = -model.conductivity_w_mk * np.diff(temperature) / dx
    conductance = model.area_m2 * model.conductivity_w_mk / dx
    half_source = model.heat_generation_w_m3 * model.area_m2 * dx / 2
    # Reactions include each boundary's share of the consistent element load.
    heat_out = (np.array([rise[1] - rise[0], rise[-2] - rise[-1]]) +
                np.array([1, -1]) * (right_surface - model.left_temperature_k) / n) * conductance + half_source
    return temperature, flux, heat_out


def _solve_thermal(model: ThermalStudy):
    n = model.elements
    heating = model.heat_generation_w_m3 * model.length_m**2 / (2*model.conductivity_w_mk)
    right_surface = model.right_temperature_k
    if right_surface is None:
        # Condense the right-end Robin boundary using the exact rod end relation.
        # Outward flux is k/L*(T_left - T_right) + generation*L/2 = h*(T_right - T_ambient).
        bi = model.right_film_coefficient_w_m2k * model.length_m / model.conductivity_w_mk
        right_surface = (model.left_temperature_k + heating + bi*model.right_ambient_temperature_k) / (1 + bi)
    coarse, _, _ = _thermal_solution(model, n, right_surface)
    temp, flux, heat_out = _thermal_solution(model, 2*n, right_surface)
    x = np.linspace(0, model.length_m, 2*n+1)
    generated = model.heat_generation_w_m3 * model.area_m2 * model.length_m
    peak = int(np.argmax(temp))
    delta = right_surface - model.left_temperature_k
    # An asymmetric temperature gradient can put the true maximum between FE nodes.
    if heating and -heating < delta < heating:
        peak_fraction = (1 + delta / heating) / 2
    else:
        peak_fraction = float(delta > 0)
    peak_temperature = model.left_temperature_k + delta*peak_fraction + heating*peak_fraction*(1-peak_fraction)
    result = {"kind": model.kind, "solver": "steady_rod_linear_fem_v1", "inputs": model.recorded_inputs(),
            "summary": {"max_nodal_temperature_k": float(temp[peak]), "peak_node_position_m": float(x[peak]),
                        "continuous_peak_temperature_k": peak_temperature, "continuous_peak_position_m": model.length_m*peak_fraction,
                        "left_outward_heat_w": float(heat_out[0]), "right_outward_heat_w": float(heat_out[1]),
                        "generated_heat_w": generated, "heat_balance_residual_w": float(heat_out.sum() - generated)},
            "traces": {"node_position_m": x.tolist(), "temperature_k": temp.tolist(),
                       "element_heat_flux_w_m2": flux.tolist()},
            "convergence": _convergence(n, (coarse[:-1]+coarse[1:])/2, temp, "K", model.convergence_tolerance_k),
            "assumptions": ["Steady one-dimensional conduction with constant conductivity and cross-sectional area.",
                            "Both end temperatures are prescribed. The lateral surface is insulated; generation is uniform.",
                            "Temperature limits use the continuous extremum of the exact uniform-source solution.",
                            "Element heat flux is positive toward increasing x; end heat is positive out of the rod."]}
    checks = [_balance_check("heat_balance_w", result["summary"]["heat_balance_residual_w"],
                             max(abs(generated), max(abs(heat_out)))),
              {"quantity": "mesh_temperature", "passed": result["convergence"]["passed"]}]
    if model.right_temperature_k is None:
        film = model.right_film_coefficient_w_m2k
        # Compute the film temperature difference before adding it to the large absolute temperature.
        surface_above_ambient = (model.left_temperature_k - model.right_ambient_temperature_k + heating) / (1 + bi)
        convective_heat = film * model.area_m2 * surface_above_ambient
        result["summary"].update(right_surface_temperature_k=right_surface, right_convective_heat_w=convective_heat)
        result["assumptions"][1] = ("The left temperature is fixed. The right end exchanges heat with a uniform ambient "
                                    "through the specified film coefficient. The lateral surface is insulated; generation is uniform.")
        checks.append(_balance_check("right_boundary_heat_w", heat_out[1] - convective_heat,
                                     max(abs(generated), max(abs(heat_out)), abs(convective_heat))))
    return _acceptance(result, [("continuous_peak_temperature_k", model.max_temperature_k)], checks)


def _response_terms(model, observation):
    """Exact reference response of each supported fixture is offset + sensitivity / property."""
    if isinstance(model, BeamStudy):
        length = model.length_m
        inertia = model.width_m * model.height_m**3 / 12
        sensitivity = (observation.tip_force_n * length**3 / 3 + model.transverse_load_n_per_m * length**4 / 8) / inertia
        return 0.0, sensitivity, observation.tip_displacement_m
    x = observation.position_m
    offset = model.left_temperature_k + (model.right_temperature_k - model.left_temperature_k) * x / model.length_m
    return offset, observation.heat_generation_w_m3 * x * (model.length_m-x)/2, observation.temperature_k


def _calibrate(study: CalibrationStudy):
    model = study.model
    offsets, slopes, measurements = np.array([_response_terms(model, item) for item in study.fit]).T
    if not np.any(slopes):
        raise ValueError("Fitting loads produce no sensitivity to the selected material property")
    if not any(_response_terms(model, item)[1] != 0 for item in study.validation):
        raise ValueError("Validation needs at least one measurement sensitive to the fitted property")
    scale = float(np.max(np.abs(slopes)))
    normalized = slopes / scale
    inverse_estimate = float(normalized @ (measurements - offsets) / (normalized @ normalized) / scale)
    low, high = study.parameter_bounds
    inverse = float(np.clip(inverse_estimate, 1/high, 1/low))
    beam = isinstance(model, BeamStudy)
    parameter = "young_modulus_pa" if beam else "conductivity_w_mk"

    def residuals(observations):
        rows = []
        for reading in observations:
            offset, sensitivity, observed = _response_terms(model, reading)
            prediction = offset + sensitivity * inverse
            rows.append({"run_id": reading.run_id, "measured": observed, "predicted": prediction,
                         "residual": prediction - observed})
        return rows

    fit, validation = residuals(study.fit), residuals(study.validation)
    validation_errors = np.array([r["residual"] for r in validation])
    validated = bool(np.max(np.abs(validation_errors)) <= study.validation_tolerance)
    return {"kind": study.kind, "solver": "bounded_inverse_property_least_squares_v1",
            "inputs": {**study.model_dump(), "model": model.recorded_inputs()}, "passed": validated,
            "summary": {"parameter": parameter, "prior_value": getattr(model, parameter), "fitted_value": 1/inverse,
                        "at_parameter_bound": inverse == 1/high or inverse == 1/low,
                        "residual_unit": "m" if beam else "K", "validation_tolerance": study.validation_tolerance,
                        "fit_rmse": float(np.sqrt(np.mean([r["residual"]**2 for r in fit]))),
                        "validation_rmse": float(np.sqrt(np.mean(validation_errors**2))),
                        "validation_max_abs_error": float(np.max(np.abs(validation_errors))), "validation_passed": validated},
            "fit": fit, "validation": validation,
            "assumptions": ["The fit minimizes equally weighted squared residuals over the declared fit runs.",
                            "Validation runs are excluded from fitting. Each run ID must identify a distinct measurement.",
                            "Only the selected scalar material property varies. Fixture geometry and boundary conditions are taken as supplied."]}


def run_engineering(request: EngineeringRequest | dict) -> dict:
    study = EngineeringRequest.model_validate(request).root
    if isinstance(study, BeamStudy):
        return _solve_beam(study)
    if isinstance(study, ThermalStudy):
        return _solve_thermal(study)
    return _calibrate(study)
