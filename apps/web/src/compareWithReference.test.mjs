import test from 'node:test';
import assert from 'node:assert/strict';
import { changedInputs, defaultPair, resolvePair, completedConditions, splitCriteria } from './campaignCompare.ts';

function condition(id, overrides = {}) {
  return {
    id, label: id, adapter: 'robot_motion', status: 'completed', error: null,
    passed: true, reference: false, coordinates: {}, metrics: {}, ...overrides,
  };
}

test('defaultPair prefers the reference on the left and a differing completed run on the right', () => {
  const runs = [
    condition('ref', { reference: true, coordinates: { payload_kg: 1 } }),
    condition('a', { coordinates: { payload_kg: 2 } }),
    condition('b', { coordinates: { payload_kg: 3 } }),
  ];
  const pair = defaultPair(runs, 'ref');
  assert.equal(pair.left, 'ref');
  assert.equal(pair.right, 'a');
  const resolved = resolvePair(runs, pair);
  assert.equal(resolved.left.id, 'ref');
  assert.equal(resolved.right.id, 'a');
});

test('defaultPair falls back to the first completed run when no reference is supplied', () => {
  const runs = [
    condition('pending', { status: 'running' }),
    condition('a'),
    condition('b'),
  ];
  assert.deepEqual(completedConditions(runs).map(r => r.id), ['a', 'b']);
  const pair = defaultPair(runs, null);
  assert.deepEqual([pair.left, pair.right], ['a', 'b']);
});

test('switching the selected left/right ids recomputes the pair and the changed-inputs diff', () => {
  const runs = [
    condition('x', { coordinates: { payload_kg: 1, speed: 'slow' } }),
    condition('y', { coordinates: { payload_kg: 2, speed: 'slow' } }),
    condition('z', { coordinates: { payload_kg: 2, speed: 'fast' } }),
  ];
  const byId = Object.fromEntries(runs.map(r => [r.id, r]));

  // only-some-keys differ: x vs y -> payload changed, speed identical
  let pair = { left: 'x', right: 'y' };
  let resolved = resolvePair(runs, pair);
  let diff = changedInputs(resolved.left.coordinates, resolved.right.coordinates);
  assert.deepEqual(diff, [{ key: 'payload_kg', left: 1, right: 2 }]);

  // switch the right picker to z -> now both payload and speed differ against x
  pair = { ...pair, right: 'z' };
  resolved = resolvePair(runs, pair);
  diff = changedInputs(resolved.left.coordinates, resolved.right.coordinates);
  assert.deepEqual(diff.map(d => d.key).sort(), ['payload_kg', 'speed']);
  assert.equal(byId[pair.right].id, 'z');

  // switch the left picker to y vs z -> only speed differs
  pair = { left: 'y', right: 'z' };
  resolved = resolvePair(runs, pair);
  diff = changedInputs(resolved.left.coordinates, resolved.right.coordinates);
  assert.deepEqual(diff, [{ key: 'speed', left: 'slow', right: 'fast' }]);
});

test('object-valued coordinates are compared structurally', () => {
  const left = { waypoints: [1, 2, 3], config: { grip: 'firm' } };
  const rightSame = { waypoints: [1, 2, 3], config: { grip: 'firm' } };
  const rightChanged = { waypoints: [1, 2, 4], config: { grip: 'firm' } };
  assert.deepEqual(changedInputs(left, rightSame), []);
  assert.deepEqual(changedInputs(left, rightChanged), [{ key: 'waypoints', left: [1, 2, 3], right: [1, 2, 4] }]);
});

test('identical runs produce an empty diff and missing keys count as changes', () => {
  const same = { payload_kg: 2, speed: 'fast' };
  assert.deepEqual(changedInputs(same, { ...same }), []);
  // a key present in only one run is a difference (undefined vs value)
  const diff = changedInputs({ payload_kg: 2 }, { payload_kg: 2, extra: true });
  assert.deepEqual(diff, [{ key: 'extra', left: undefined, right: true }]);
});

test('splitCriteria separates boolean checks, numeric limits and nested objects without dropping any', () => {
  // mirrors robot_motion's criteria shape (project_robot.py), including the nested servo_response.
  const criteria = {
    joint_target_tolerance: 0.02,
    check_all_joint_position_and_velocity_limits: true,
    qualification_required: false,
    servo_response: { joint: 'left_knuckle', time_constant_s: 0.1, effective_gain_per_s: 10 },
  };
  const { checks, limits, nested } = splitCriteria(criteria);
  assert.deepEqual(checks.map(([k]) => k).sort(),
    ['check_all_joint_position_and_velocity_limits', 'qualification_required']);
  assert.deepEqual(limits, [['joint_target_tolerance', 0.02]]);
  // the object-valued criterion must be surfaced, not discarded
  assert.deepEqual(nested, [['servo_response',
    { joint: 'left_knuckle', time_constant_s: 0.1, effective_gain_per_s: 10 }]]);

  // every input key is accounted for across exactly one bucket
  const covered = [...checks, ...limits, ...nested].map(([k]) => k).sort();
  assert.deepEqual(covered, Object.keys(criteria).sort());
});

test('splitCriteria tolerates empty/undefined criteria and non-finite numbers', () => {
  assert.deepEqual(splitCriteria(undefined), { checks: [], limits: [], nested: [] });
  assert.deepEqual(splitCriteria({}), { checks: [], limits: [], nested: [] });
  // NaN/Infinity are not finite limits, and arrays count as nested objects
  const { limits, nested } = splitCriteria({ bad: NaN, inf: Infinity, waypoints: [1, 2] });
  assert.deepEqual(limits, []);
  assert.deepEqual(nested, [['waypoints', [1, 2]]]);
});
