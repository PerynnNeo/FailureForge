import test from 'node:test';
import assert from 'node:assert/strict';
import { axisValues, cellOutcome, liftHoldTrace, millimetres } from './environmentConditions.ts';

test('environment axes accept increasing decimal coordinates with a physical zero', () => {
  assert.deepEqual(axisValues('0, .25, 5e-1', 'payload'), [0, 0.25, 0.5]);
  for (const input of ['', '1', '-1, 0', '0, 0', '1, 0', '0, 0x10', '0, Infinity']) {
    assert.throws(() => axisValues(input, 'payload'), /payload/);
  }
});

test('environment outcomes preserve missing, blocked and unassessed conditions', () => {
  assert.equal(cellOutcome(), 'Missing');
  assert.equal(cellOutcome({ status: 'invalid', passed: false, error: 'Out of scope' }), 'Blocked');
  assert.equal(cellOutcome({ status: 'running', passed: null, error: null }), 'Running');
  assert.equal(cellOutcome({ status: 'completed', passed: null, error: null }), 'Unassessed');
  assert.equal(cellOutcome({ status: 'completed', passed: false, error: null }), 'Failed');
  assert.equal(millimetres(undefined), '—');
  assert.equal(millimetres(0.00981), '9.81 mm');
});

test('hold trace uses recorded time bounds, target and millimetre tolerance', () => {
  const result = { fixture: { arrival_deadline_s: 0.5, end_time_s: 1.25, target_m: 0.25, error_limit_m: 0.015 },
    series: { time_s: [0, 0.5, 0.75, 1.25, 2], position_m: [0, 0.24, 0.27, 0.245, 1] },
    passed: false, criteria: { held_within_tolerance: false } };
  const trace = liftHoldTrace(result);
  assert.ok(trace.showFirst);
  assert.deepEqual(trace.samples.map(sample => sample.step), [0, 0.25, 0.75]);
  assert.deepEqual(trace.samples.map(sample => Math.round(sample['absolute height error (mm)'])), [10, 20, 5]);
  assert.deepEqual(trace.samples.map(sample => sample['allowed error (mm)']), [15, 15, 15]);
  assert.equal(liftHoldTrace({ ...result, criteria: { held_within_tolerance: true } }).showFirst, false);
  assert.equal(liftHoldTrace({ ...result, passed: null }).showFirst, false);
  assert.equal(liftHoldTrace({ ...result, fixture: { ...result.fixture, end_time_s: 0.5 } }), null);
  assert.equal(liftHoldTrace({ ...result, fixture: { ...result.fixture, error_limit_m: null } }), null);
  assert.equal(liftHoldTrace({ ...result, series: { ...result.series, position_m: [0] } }), null);
});
