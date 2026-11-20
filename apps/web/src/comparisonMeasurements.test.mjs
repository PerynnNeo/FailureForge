import assert from 'node:assert/strict';
import test from 'node:test';
import { comparisonMeasurements } from './comparisonMeasurements.ts';

test('the loaded lift compares the saved hold error and tolerance in millimetres', () => {
  const run = { adapter: 'packaging_lift', inputs: {}, result: {
    fixture: { speed_limit_m_s: 2 }, criteria: { held_within_tolerance: false, arrived_within_tolerance: true },
    summary: { max_hold_error_m: .0139491, arrival_error_m: .009, error_limit_m: .01, peak_speed_m_s: .6 },
  } };
  const { measurements } = comparisonMeasurements(run);
  const [hold, arrival, speed] = measurements;
  assert.equal(hold.name, 'Maximum hold error');
  assert.ok(Math.abs(hold.value - 13.9491) < 1e-9);
  assert.equal(hold.maximum, 10);
  assert.equal(hold.unit, 'mm');
  assert.equal(hold.passed, false);
  assert.equal(arrival.passed, true);
  assert.equal(speed.maximum, 2);
  assert.equal(speed.unit, 'm/s');
});

test('beam and rod acceptance rows preserve saved numerical limits and verdicts', () => {
  const saved = (quantity, measured, maximum) => ({ inputs: {}, result: { acceptance_checks: [
    { quantity, measured, maximum, passed: false },
  ] } });
  const rod = comparisonMeasurements({ adapter: 'thermal_rod', ...saved('continuous_peak_temperature_k', 320, 315) });
  assert.deepEqual(rod.measurements[0], { name: 'Continuous peak temperature', value: 320, maximum: 315, unit: 'K', passed: false });
  const beam = comparisonMeasurements({ adapter: 'structural_beam', ...saved('continuous_max_surface_stress_pa', 2e7, 1.5e7) });
  assert.equal(beam.measurements[0].value, 20);
  assert.equal(beam.measurements[0].maximum, 15);
  assert.equal(beam.measurements[0].unit, 'MPa');
});

test('timed lift results preserve both phase verdicts when the overall outcome matches', () => {
  const read = (arrival, passed) => comparisonMeasurements({
    adapter: 'packaging_lift_timed_v2', inputs: {}, result: { passed: false,
      criteria: { held_within_tolerance: false, arrived_within_tolerance: passed },
      summary: { arrival_error_m: arrival, max_hold_error_m: .013949, error_limit_m: .01 },
    },
  }).measurements.map(row => [row.name, row.unit, row.passed]);
  assert.deepEqual(read(.00981, true), [['Maximum hold error', 'mm', false], ['Arrival error', 'mm', true]]);
  assert.deepEqual(read(.013949, false), [['Maximum hold error', 'mm', false], ['Arrival error', 'mm', false]]);
});

test('robot intent flags never become recorded outcomes, and radians and metres stay distinct', () => {
  const run = { adapter: 'robot_motion', inputs: {}, result: {
    criteria: { qualification_required: false, check_all_joint_position_and_velocity_limits: true, joint_target_tolerance: .002 },
    model: { joints: [{ name: 'q', unit: 'rad', velocity_limit: 2 }, { name: 'slide', unit: 'm', velocity_limit: .5 }] },
    metrics: { final_absolute_joint_error: { q: .001, slide: .0015 }, peak_joint_speed: { q: 3, slide: .1 },
      within_joint_limits: true, within_velocity_limits: false, target_reached: true },
  } };
  const { measurements, outcomes } = comparisonMeasurements(run);
  assert.deepEqual(outcomes.map(item => item.passed), [true, true, false]);
  assert.deepEqual(measurements.map(item => [item.value, item.maximum, item.unit]),
    [[.001,.002,'rad'], [3,2,'rad/s'], [.0015,.002,'m'], [.1,.5,'m/s']]);
});

test('calibration limits follow the recorded validation metric and units', () => {
  const joint = comparisonMeasurements({ adapter: 'joint_response', inputs: { max_validation_rmse_rad: .02 },
    result: { summary: { validation_rmse_rad: .002844 } } });
  assert.equal(joint.measurements[0].maximum, .02);
  assert.equal(joint.measurements[0].unit, 'rad');
  const material = comparisonMeasurements({ adapter: 'calibration', inputs: {},
    result: { summary: { validation_rmse: .2, validation_max_abs_error: .3, validation_tolerance: .25,
      residual_unit: 'K', validation_passed: false } } });
  assert.deepEqual(material.measurements[0], { name:'Maximum held-out error', value:.3, maximum:.25, unit:'K', passed:false });
});

test('measurements without a declared threshold stay measurement-only', () => {
  const run = { adapter:'cad_inventory', inputs:{}, result:{ summary:{ triangles:3, surface_area_m2:.2 } } };
  const { measurements, outcomes } = comparisonMeasurements(run);
  assert.deepEqual(outcomes, []);
  assert.equal(measurements.length, 2);
  assert.equal(measurements[1].unit, 'm²');
  assert.ok(measurements.every(row => row.maximum === undefined && row.passed === undefined));
});
