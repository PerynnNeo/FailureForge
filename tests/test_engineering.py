import math

import numpy as np
import pytest
from pydantic import ValidationError

from failureforge.engineering import EngineeringRequest, run_engineering


BEAM = {"kind": "structural_beam", "length_m": 1.2, "height_m": 0.04, "width_m": 0.03,
        "young_modulus_pa": 200e9, "tip_force_n": -30., "elements": 4}
ROD = {"kind": "thermal_rod", "length_m": 2., "area_m2": 0.001, "conductivity_w_mk": 80.,
       "left_temperature_k": 300., "right_temperature_k": 320., "elements": 4}


def test_beam_tip_load_reference():
    p, length, modulus = BEAM["tip_force_n"], BEAM["length_m"], BEAM["young_modulus_pa"]
    inertia = BEAM["width_m"] * BEAM["height_m"]**3 / 12
    study = run_engineering(EngineeringRequest.model_validate(BEAM))
    summary = study["summary"]
    assert summary["tip_displacement_m"] == pytest.approx(p * length**3 / (3 * modulus * inertia))
    assert summary["tip_rotation_rad"] == pytest.approx(p * length**2 / (2 * modulus * inertia))
    assert summary["root_reaction_n"] == pytest.approx(-p)
    assert summary["root_reaction_moment_nm"] == pytest.approx(-p * length)
    assert summary["max_surface_bending_stress_pa"] == pytest.approx(abs(p) * length * BEAM["height_m"] / (2 * inertia))
    assert summary["within_small_deflection_screen"]
    assert len(study["traces"]["displacement_m"]) == 2*BEAM["elements"]+1
    assert study["convergence"]["max_abs_change"] < 1e-11


def test_uniform_beam_load_converges_at_element_interiors():
    q, length = 100., BEAM["length_m"]
    model = {**BEAM, "distributed_load_n_per_m": q, "tip_force_n": 0}
    coarse, fine = [run_engineering({**model, "elements": n}) for n in (2, 4)]
    inertia = model["width_m"] * model["height_m"]**3 / 12
    assert fine["summary"]["tip_displacement_m"] == pytest.approx(q * length**4 / (8*model["young_modulus_pa"]*inertia))
    assert fine["summary"]["root_reaction_n"] == pytest.approx(-q*length)
    assert fine["summary"]["root_reaction_moment_nm"] == pytest.approx(-q*length**2/2)
    assert fine["convergence"]["max_abs_change"] == pytest.approx(coarse["convergence"]["max_abs_change"]/16)
    high_load = run_engineering({**BEAM, "tip_force_n": 1e5})
    assert not high_load["summary"]["within_small_deflection_screen"]


def test_heat_rod_known_boundary_gradient_and_energy_balance():
    study = run_engineering(ROD)
    trace = study["traces"]
    x = np.array(trace["node_position_m"])
    np.testing.assert_allclose(trace["temperature_k"], 300 + 10*x)
    np.testing.assert_allclose(trace["element_heat_flux_w_m2"], -800)
    assert study["summary"]["left_outward_heat_w"] == pytest.approx(.8)
    assert study["summary"]["right_outward_heat_w"] == pytest.approx(-.8)
    assert study["summary"]["heat_balance_residual_w"] == pytest.approx(0)
    with_source = {**ROD, "right_temperature_k": 300, "heat_generation_w_m3": 800}
    coarse, fine = [run_engineering({**with_source, "elements": n}) for n in (2, 4)]
    x = np.array(fine["traces"]["node_position_m"])
    np.testing.assert_allclose(fine["traces"]["temperature_k"], 300 + 5*x*(2-x))
    assert fine["summary"]["max_nodal_temperature_k"] == pytest.approx(305)
    assert fine["summary"]["left_outward_heat_w"] == pytest.approx(.8)
    assert fine["summary"]["right_outward_heat_w"] == pytest.approx(.8)
    assert fine["summary"]["heat_balance_residual_w"] == pytest.approx(0)
    assert fine["convergence"]["max_abs_change"] == pytest.approx(coarse["convergence"]["max_abs_change"]/4)


def test_uniform_pressure_superposes_with_line_and_tip_loads():
    pressure, line, tip = -600.0, 4.0, 2.0
    result = run_engineering({**BEAM, "face_pressure_pa": pressure,
                              "distributed_load_n_per_m": line, "tip_force_n": tip})
    q = pressure * BEAM["width_m"] + line
    length = BEAM["length_m"]
    ei = BEAM["young_modulus_pa"] * BEAM["width_m"] * BEAM["height_m"]**3 / 12
    summary = result["summary"]
    assert summary["tip_displacement_m"] == pytest.approx((tip*length**3/3 + q*length**4/8) / ei)
    assert summary["root_reaction_n"] == pytest.approx(-(tip + q*length))
    assert summary["continuous_max_abs_displacement_m"] == pytest.approx(abs(summary["tip_displacement_m"]))
    assert summary["total_distributed_load_n_per_m"] == pytest.approx(q)
    assert result["numerical_diagnostics"]["passed"]
    assert "face_pressure_pa" not in run_engineering(BEAM)["inputs"]


def test_right_end_convection_matches_energy_and_continuous_peak_under_heating():
    # A 1 m rod with k=10, T_left=300 and q=1000 has T(x)=300+30x-50x²
    # for a 270 K fluid and h=70. The surface is 280 K and the peak is 304.5 K at x=0.3.
    rod = {k: v for k, v in ROD.items() if k != "right_temperature_k"}
    model = {**rod, "length_m": 1., "conductivity_w_mk": 10., "heat_generation_w_m3": 1000.,
             "right_ambient_temperature_k": 270., "right_film_coefficient_w_m2k": 70.,
             "max_temperature_k": 304.45, "elements": 2}
    result = run_engineering(model)
    x = np.array(result["traces"]["node_position_m"])
    np.testing.assert_allclose(result["traces"]["temperature_k"], 300 + 30*x - 50*x**2)
    s = result["summary"]
    assert s["continuous_peak_position_m"] == pytest.approx(.3)
    assert s["continuous_peak_temperature_k"] == pytest.approx(304.5)
    assert s["max_nodal_temperature_k"] < 304.45
    assert s["right_convective_heat_w"] == pytest.approx(.7)
    assert s["right_outward_heat_w"] == pytest.approx(.7)
    assert s["left_outward_heat_w"] == pytest.approx(.3)
    assert result["numerical_diagnostics"]["passed"] and result["passed"] is False
    assert "right_temperature_k" not in result["inputs"]
    assert "right_ambient_temperature_k" not in run_engineering(ROD)["inputs"]
    insulated = run_engineering({**model, "right_film_coefficient_w_m2k": 0.})
    assert insulated["summary"]["continuous_peak_temperature_k"] == pytest.approx(350.)
    assert insulated["summary"]["right_outward_heat_w"] == pytest.approx(0.)
    hot_air = run_engineering({**model, "heat_generation_w_m3": 0., "right_ambient_temperature_k": 340.})
    assert hot_air["summary"]["right_surface_temperature_k"] == pytest.approx(335.)
    assert hot_air["summary"]["right_convective_heat_w"] == pytest.approx(-.35)


@pytest.mark.parametrize("boundary", [
    {}, {"right_ambient_temperature_k": 290}, {"right_film_coefficient_w_m2k": 10},
    {"right_temperature_k": 300, "right_ambient_temperature_k": 300, "right_film_coefficient_w_m2k": 10},
    {"right_ambient_temperature_k": 290, "right_film_coefficient_w_m2k": -1},
])
def test_right_end_rejects_ambiguous_or_unphysical_boundary_conditions(boundary):
    fixed_left = {k: v for k, v in ROD.items() if k != "right_temperature_k"}
    with pytest.raises(ValidationError):
        run_engineering({**fixed_left, **boundary})


def beam_calibration():
    def reading(run_id, force):
        inertia = BEAM["width_m"] * BEAM["height_m"]**3 / 12
        return {"run_id": run_id, "tip_force_n": force, "tip_displacement_m": force * BEAM["length_m"]**3 / (3 * 75e9 * inertia)}

    return {"kind": "calibration", "model": BEAM, "parameter_bounds": [1e9, 250e9], "validation_tolerance": 0.0001,
            "fit": [reading("load A", -10.), reading("load B", -30.)], "validation": [reading("load C", -40.)]}


def test_beam_calibration_keeps_holdout_out_of_fit_and_reports_bounds():
    calibration = beam_calibration()
    result = run_engineering(calibration)
    assert result["summary"]["fitted_value"] == pytest.approx(75e9)
    assert result["summary"]["validation_passed"]
    calibration["validation"][0]["tip_displacement_m"] *= 3
    held_out_error = run_engineering(calibration)
    assert held_out_error["summary"]["fitted_value"] == result["summary"]["fitted_value"]
    assert not held_out_error["summary"]["validation_passed"]
    clamped = run_engineering({**calibration, "parameter_bounds": [1e9, 50e9]})
    assert clamped["summary"]["fitted_value"] == pytest.approx(50e9)
    assert clamped["summary"]["at_parameter_bound"]


def test_thermal_calibration_recovers_known_k_from_internal_temperatures():
    def reading(identifier, x, q):
        return {"run_id": identifier, "position_m": x, "heat_generation_w_m3": q,
                "temperature_k": 300+10*x+q*x*(2-x)/(2*20)}

    study = {"kind": "calibration", "model": ROD, "parameter_bounds": [1, 100], "validation_tolerance": 0.05,
             "fit": [reading("fit A", .7, 100), reading("fit B", .9, 200)],
             "validation": [reading("validation A", .4, 90)]}
    result = run_engineering(study)
    assert result["summary"]["fitted_value"] == pytest.approx(20)
    assert result["summary"]["validation_passed"]
    assert result["summary"]["residual_unit"] == "K"
    model = {k: v for k, v in ROD.items() if k != "right_temperature_k"}
    model.update(right_ambient_temperature_k=300., right_film_coefficient_w_m2k=10.)
    with pytest.raises(ValidationError, match="two prescribed end temperatures"):
        run_engineering({**study, "model": model})


def test_acceptance_thresholds_and_independent_mesh_diagnostics():
    reference = run_engineering(ROD)
    assert reference["passed"] is None and reference["numerical_diagnostics"]["passed"]
    hot_rod = {**ROD, "right_temperature_k": 300, "heat_generation_w_m3": 800}
    assert run_engineering({**hot_rod, "max_temperature_k": 304})["passed"] is False
    assert run_engineering({**hot_rod, "max_temperature_k": 306, "convergence_tolerance_k": 2})["passed"] is True
    underresolved = run_engineering({**hot_rod, "max_temperature_k": 310, "convergence_tolerance_k": .0001})
    assert underresolved["acceptance_checks"][0]["passed"]
    assert underresolved["passed"] is None and not underresolved["numerical_diagnostics"]["passed"]
    acceptable = {**BEAM, "max_displacement_m": .1, "max_surface_stress_pa": 1e9,
                  "convergence_tolerance_m": .0001, "stress_convergence_tolerance_pa": 1e4}
    assert run_engineering(acceptable)["passed"] is True
    assert run_engineering({**acceptable, "max_surface_stress_pa": 1e4})["passed"] is False
    assert run_engineering({**acceptable, "distributed_load_n_per_m": 200,
                            "stress_convergence_tolerance_pa": 1})["numerical_diagnostics"]["passed"] is False


def test_design_limits_catch_interior_extrema_between_mesh_nodes():
    thermal = run_engineering({**ROD, "right_temperature_k": 302.2, "heat_generation_w_m3": 800.,
                               "elements": 2, "max_temperature_k": 306.13})
    assert thermal["summary"]["max_nodal_temperature_k"] < 306.13
    assert thermal["summary"]["continuous_peak_temperature_k"] == pytest.approx(306.1605)
    assert thermal["passed"] is False
    beam = run_engineering({**BEAM, "distributed_load_n_per_m": 100., "tip_force_n": -50., "elements": 2})
    inertia = BEAM["width_m"] * BEAM["height_m"]**3 / 12
    assert beam["summary"]["continuous_max_surface_stress_pa"] == pytest.approx(12.5 * BEAM["height_m"] / (2 * inertia))


def test_off_grid_point_and_patch_match_independent_cantilever_influence_function():
    # A transverse point at a changes the tip displacement by F a²(3L-a)/(6EI).
    # Integrate this Green function over the patch analytically; compare both
    # the FE nodes and the maximum from the independent piecewise equilibrium path.
    inputs = {**BEAM, "tip_force_n": 0., "elements": 5, "span_loads": [
        {"start_fraction": .193, "end_fraction": .193, "force_n": 1.75},
        {"start_fraction": .419, "end_fraction": .826, "force_n": 2.25}]}
    out = run_engineering(inputs)
    length = inputs["length_m"]
    inertia = inputs["width_m"]*inputs["height_m"]**3/12
    def primitive(x):
        return x**3 - x**4/4
    point = 1.75*.193**2*(3-.193)
    patch = 2.25*(primitive(.826)-primitive(.419))/(.826-.419)
    expected = (point+patch)*length**3/(6*inputs["young_modulus_pa"]*inertia)
    moment = (1.75*.193 + 2.25*(.419+.826)/2)*length
    summary = out["summary"]
    assert out["solver"] == "euler_bernoulli_span_loads_v2" and out["numerical_diagnostics"]["passed"]
    assert summary["continuous_max_abs_displacement_m"] == pytest.approx(expected, rel=2e-12)
    assert summary["tip_displacement_m"] == pytest.approx(expected, rel=1e-8)
    assert summary["continuous_max_surface_stress_pa"] == pytest.approx(moment*inputs["height_m"]/(2*inertia))
    assert summary["root_reaction_n"] == pytest.approx(-4.) and summary["root_reaction_moment_nm"] == pytest.approx(-moment)


def test_mixed_sign_span_loads_match_legacy_continuous_extrema_and_convergence():
    loads = {**BEAM, "tip_force_n": -45., "distributed_load_n_per_m": 100., "elements": 5}
    legacy = run_engineering(loads)
    result = run_engineering({**loads, "distributed_load_n_per_m": 0., "span_loads": [
        {"start_fraction": a, "end_fraction": b, "force_n":100*loads["length_m"]*(b-a)}
        for a, b in ((0., .23), (.23, .71), (.71, 1.))]})
    for name in ("continuous_max_abs_displacement_m", "continuous_max_surface_stress_pa", "tip_displacement_m",
                 "root_reaction_moment_nm", "root_reaction_n"):
        assert result["summary"][name] == pytest.approx(legacy["summary"][name], rel=2e-8, abs=1e-10)
    assert result["convergence"]["max_abs_change"] == pytest.approx(legacy["convergence"]["max_abs_change"], abs=1e-12)


@pytest.mark.parametrize("start,end", [(.5,.49), (-.001,.6), (.61,1.001), (.2,.200000001)])
def test_local_load_intervals_are_bounded(start, end):
    with pytest.raises(ValidationError):
        run_engineering({**BEAM, "span_loads": [{"start_fraction": start, "end_fraction": end, "force_n": 2.}]})


@pytest.mark.parametrize("bad", [
    {**ROD, "kind": "thermal_3d"}, {**ROD, "heat_generation_w_m3": math.inf},
    {**ROD, "elements": True}, {**ROD, "right_temperature_k": -1}, {**ROD, "area_m2": 0},
    {**ROD, "conductivity_w_mk": 0}, {**BEAM, "height_m": 1}, {**BEAM, "young_modulus_pa": -1},
    {**BEAM, "tip_force_n": math.nan}, {**BEAM, "support": "pinned"}, {**BEAM, "elements": 129},
])
def test_unsupported_physics_and_invalid_inputs_rejected(bad):
    with pytest.raises(ValidationError):
        run_engineering(bad)


def test_calibration_rejects_data_leakage_and_uninformative_measurements():
    study = beam_calibration()
    with pytest.raises(ValueError, match="distinct run ID"):
        run_engineering({**study, "validation": [study["fit"][0]]})
    with pytest.raises(ValueError, match="no sensitivity"):
        run_engineering({**study, "fit": [{"run_id": "zero", "tip_force_n": 0, "tip_displacement_m": 0}]})
    with pytest.raises(ValueError, match="sensitive"):
        run_engineering({**study, "validation": [{"run_id": "zero", "tip_force_n": 0, "tip_displacement_m": 0}]})
    with pytest.raises(ValueError, match="inside"):
        run_engineering({**study, "model": ROD, "parameter_bounds": [1, 100],
                         "fit": [{"run_id": "end", "position_m": 2, "temperature_k": 320, "heat_generation_w_m3": 50}],
                         "validation": [{"run_id": "holdout", "position_m": 1, "temperature_k": 310, "heat_generation_w_m3": 50}]})
