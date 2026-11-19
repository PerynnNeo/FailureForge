import numpy as np
import pytest

from failureforge.project_camera_fields import field_scene


def test_thermal_views_track_recorded_spatial_stations_and_keep_steady_field_fixed():
    run = {'adapter': 'thermal_rod', 'result': {'inputs': {'area_m2': np.pi * 0.01**2},
           'traces': {'node_position_m': [0, 0.20, 0.31], 'temperature_k': [293., 330., 305.]}}}
    scene = field_scene(run)
    assert scene.view_labels == ('Whole rod', 'Section inspection')
    assert 'Steady' in scene.description and '293 K' in scene.description and '330 K' in scene.description
    assert scene.objects[0].size[0] == pytest.approx(0.01)
    assert scene.objects[0].color[2] > scene.objects[1].color[2]
    assert sum(2 * part.size[1] for part in scene.objects[:-1]) == pytest.approx(0.31)
    start, middle, end = [scene.frame(t * scene.duration_s) for t in (0, 0.64, 1)]
    assert middle.positions[-1, 0] == 0.20 and end.positions[-1, 0] == 0.31
    np.testing.assert_allclose(start.positions[:-1], end.positions[:-1])
    np.testing.assert_allclose(start.cameras[0].eye, end.cameras[0].eye)
    np.testing.assert_allclose(middle.cameras[1].target, middle.positions[-1])
    np.testing.assert_allclose(start.rotations[0] @ [0, 0, 1], [1, 0, 0])


def test_beam_signed_shape_uses_saved_dimensions_and_disclosed_display_gain():
    run = {'adapter': 'structural_beam', 'inputs': {'width_m': 0.08, 'height_m': 0.02},
           'result': {'traces': {'node_position_m': [0, 0.5, 1], 'displacement_m': [0, -0.001, -0.003]}}}
    scene = field_scene(run)
    assert '25×' in scene.description
    first, last = scene.frame(0), scene.frame(scene.duration_s)
    assert last.positions[-1, 2] == pytest.approx(-0.075)
    np.testing.assert_allclose(first.positions[:-1], last.positions[:-1])
    assert scene.objects[0].size[1:3] == (0.04, 0.01)
    assert scene.frame(0).rotations[0, 2, 0] < 0


def test_cad_preview_is_exact_and_only_its_view_orbits():
    triangle = [[0., 0., 0.], [0., 1., 0.], [0., 0., 2.]]
    run = {'adapter': 'cad_inventory', 'result': {'preview_triangles_m': [triangle], 'summary': {'triangles': 2500}}}
    scene = field_scene(run)
    assert '1 of 2500' in scene.description
    first, later = scene.frame(0), scene.frame(scene.duration_s/3)
    np.testing.assert_allclose(scene.objects[0].vertices + first.positions[0], triangle)
    np.testing.assert_allclose(first.positions, later.positions)
    np.testing.assert_allclose(first.cameras[1].eye, later.cameras[1].eye)
    assert not np.allclose(first.cameras[0].eye, later.cameras[0].eye)


def test_cad_uses_verified_original_and_declared_units_when_supplied():
    stl = b"""solid plate
facet normal 0 0 1
outer loop
vertex 0 0 0
vertex 20 0 0
vertex 0 30 0
endloop
endfacet
endsolid plate
"""
    run = {'adapter': 'cad_inventory', 'inputs': {'units': 'mm', 'cad_asset_id': 'asset-fixture'},
           'result': {'summary': {'triangles': 1}}}
    scene = field_scene(run, stl)
    assert 'All 1 triangles' in scene.description
    original = scene.objects[0].vertices + scene.frame(0).positions[0]
    np.testing.assert_allclose(original.max(axis=0), [0.02, 0.03, 0.])
    assert field_scene(run, b'invalid') is None


def test_angle_fixture_uses_saved_irregular_clock_and_distinguishes_measured_from_fitted():
    run = {'adapter': 'joint_response', 'result': {'traces': {'validation': {
        'time_s': [20., 20.2, 21.], 'position_rad': [0., np.pi/2, np.pi], 'predicted_rad': [0., 0., 0.]}}}}
    scene = field_scene(run)
    assert scene.duration_s == 1.
    assert 'Illustrative angle gauge' in scene.description and 'held-out' in scene.description
    before, after = scene.frame(0.1), scene.frame(0.3)
    np.testing.assert_allclose(before.rotations[1] @ [1,0,0], [1,0,0])
    np.testing.assert_allclose(after.rotations[1] @ [1,0,0], [0,1,0], atol=1e-12)
    np.testing.assert_allclose(after.rotations[2], np.eye(3))


def test_missing_geometry_and_unordered_fields_do_not_generate_camera_footage():
    assert field_scene({'adapter': 'calibration', 'result': {'validation': [{'measured': 1}]}}) is None
    assert field_scene({'adapter': 'thermal_rod', 'result': {'traces':
        {'node_position_m': [0,0], 'temperature_k': [300,310]}, 'inputs': {'area_m2': 1}}}) is None
    assert field_scene({'adapter': 'joint_response', 'result': {'traces': {'validation': {
        'time_s': [0,1], 'position_rad': ['0','1']}}}}) is None


def test_material_beam_comparison_keeps_discrete_measured_and_predicted_offsets():
    run = {'adapter': 'calibration', 'result': {'validation': [
        {'run_id': 'a', 'measured': 0.001, 'predicted': 0.002},
        {'run_id': 'b', 'measured': -0.004, 'predicted': -0.003}],
        'inputs': {'model': {'kind': 'structural_beam', 'length_m': 0.1, 'width_m': 0.01, 'height_m': 0.005}}}}
    scene = field_scene(run)
    assert '3×' in scene.description and '2 of 2 independent held-out' in scene.description
    a, still_a, b = [scene.frame(scene.duration_s*t) for t in (0., 0.49, 0.51)]
    np.testing.assert_allclose(a.positions, still_a.positions)
    np.testing.assert_allclose(a.positions[1:, 2], [0.003, 0.006])
    np.testing.assert_allclose(b.positions[1:, 2], [-0.012, -0.009])
    np.testing.assert_allclose(a.positions[:1], b.positions[:1])


def test_thermal_validation_joins_saved_sensor_position_by_observation_id():
    run = {'adapter': 'calibration', 'inputs': {
        'model': {'kind': 'thermal_rod', 'length_m': 0.1, 'area_m2': 0.0001},
        'validation': [{'run_id':'second','position_m':0.065}, {'run_id':'first','position_m':0.012}]},
        'result': {'validation':[{'run_id':'first', 'measured': 300., 'predicted': 330.},
                                 {'run_id':'second', 'measured': 330., 'predicted': 300.}]}}
    scene = field_scene(run)
    a, b = scene.frame(0.), scene.frame(scene.duration_s)
    np.testing.assert_allclose(a.positions[1:,0], 0.012)
    np.testing.assert_allclose(b.positions[1:,0], 0.065)
    np.testing.assert_allclose(a.colors[1:], b.colors[1:][::-1])
    assert 'sphere shows measured' in scene.description
    run['inputs']['validation'].pop()
    assert field_scene(run) is None
