import test from 'node:test';
import assert from 'node:assert/strict';
import { engineeringTracks, frameCoordinate, sampleAt, seekTime } from './recordedEventTracks.ts';
import { fieldColor, fieldDomain } from './recordedFields.ts';

const run = (adapter, result) => ({ status: 'completed', adapter, inputs: {}, result });
const lift = run('packaging_lift_timed_v2', {
  fixture: { target_m: 0, arrival_deadline_s: 1, end_time_s: 2, error_limit_m: .010 },
  series: { time_s: [0, .917, 1, 1.03, 1.105, 2, 2.02], position_m: [.4, .1, .010, -.010, -.011, 0, .2] },
  summary: { max_hold_error_m: .012 },
});
const rod = run('thermal_rod', { kind: 'thermal_rod', inputs: { max_temperature_k: 315 },
  traces: { node_position_m: [0, .03, .041, .19], temperature_k: [290, 315, 317, 313] },
  summary: { continuous_peak_temperature_k: 317.1, continuous_peak_position_m: .045 } });

test('lift uses only recorded hold samples, strict tolerance, real targets and irregular times', () => {
  const [t] = engineeringTracks(lift);
  assert.deepEqual(t.x, [1, 1.03, 1.105, 2]);
  assert.deepEqual(t.y, [10, 10, 11, 0]);
  assert.equal(t.limit, 10); assert.equal(t.first, 2);
  assert.equal(sampleAt(t, .999), -1);
  assert.equal(sampleAt(t, 1.101), 1);
  const before = { ...lift.result, fixture: { ...lift.result.fixture, target_m: .05 } };
  assert.equal(engineeringTracks(run('packaging_lift', before))[0].first, 0);
  assert.deepEqual(engineeringTracks({ ...lift, assessment_error: 'inconclusive' }), []);
});

test('thermal first above is a station. An inter-station peak never creates a fake sampled crossing', () => {
  const [t] = engineeringTracks(rod);
  assert.equal(t.axis, 'position'); assert.equal(t.x[t.first], .041); assert.equal(t.y[t.first], 317);
  assert.equal(sampleAt(t, .028), 1);
  const below = { ...rod.result, inputs: { max_temperature_k: 317 } };
  const [between] = engineeringTracks(run('thermal_rod', below));
  assert.equal(between.first, -1); assert.equal(between.peakPosition, .045); assert.ok(between.peak > between.limit);
  const [noLimit] = engineeringTracks(run('thermal_rod', { ...below, inputs: {} }));
  assert.equal(noLimit.limit, undefined); assert.equal(noLimit.first, -1);
  assert.deepEqual(engineeringTracks(run('thermal_rod', { ...below, traces: { node_position_m: [0,0], temperature_k: [1,2] }})), []);
});

test('camera jump and readout respect the discrete video clock', () => {
  const [t] = engineeringTracks(lift);
  const seconds = seekTime(t, t.x[t.first], 1, 20);
  const coordinate = frameCoordinate(t, seconds, 1, 20);
  assert.ok(coordinate >= 1.105); assert.equal(sampleAt(t, coordinate), 2);
  assert.equal(frameCoordinate(t, 1, 1, 20), t.end);
  assert.equal(frameCoordinate(t, .1, 1, 0), undefined);
  const [s] = engineeringTracks(rod);
  assert.ok(Math.abs(frameCoordinate(s, seekTime(s, .041, 5, 100), 5, 100) - .041) < .001);
});

test('beam tracks use largest absolute surface reading at element interfaces', () => {
  const b = run('structural_beam', { kind: 'structural_beam',
    inputs: { max_displacement_m: .003, max_surface_stress_pa: 1e6 },
    traces: { node_position_m: [0,.2,.4], displacement_m: [0,-.003,.004],
      element_left_surface_stress_pa: [1e6, -2e6], element_right_surface_stress_pa: [-1e6,0] } });
  const [deflection, stress] = engineeringTracks(b);
  assert.equal(deflection.first, 2); assert.equal(stress.first, 1); assert.deepEqual(stress.y, [1,2,0]);
});

test('thermal colors use a common absolute scale including a limit outside both fields', () => {
  const domain = fieldDomain([{values: [293, 310, 300]}, {values:[310, 319, 314]}], [315, 325]);
  assert.deepEqual(domain, [293, 325]);
  assert.equal(fieldColor(309, ...domain), 'rgb(51, 171, 184)');
  assert.equal(fieldColor(325, ...domain), 'rgb(240, 94, 20)');
});
