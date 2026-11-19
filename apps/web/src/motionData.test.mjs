import test from 'node:test';
import assert from 'node:assert/strict';
import { frameAt, projectPoint, readLinks, readMotion } from './motionData.ts';

test('playback chooses real samples at irregular timestamps, including both endpoints', () => {
  const times = [30, 30.05, 32, 38.2];
  assert.deepEqual([0, 30, 30.049, 30.05, 31.98, 32, 38.2, 39].map(t => frameAt(times, t)), [0, 0, 0, 1, 1, 2, 3, 3]);
});

test('the lift preserves force steps, recorded target and travel units', () => {
  const series = { time_s: [0, 0.6, 1, 2], position_m: [0, 0.11, 0.15, 0.141],
    applied_head_force_n: [0, 0, 2, 2], actuator_force_n: [30, 22, 12, 11] };
  const fixture = { target_m: 0.15, error_limit_m: 0.01, arrival_deadline_s: 1 };
  const data = readMotion({ fixture, series, summary: { payload_kg: 0.5 } });
  assert.equal(data.kind, 'lift');
  assert.equal(data.head[frameAt(data.times, 0.99)], 0);
  assert.equal(data.head[frameAt(data.times, 1)], 2);
  assert.equal(data.tolerance, .01);
  assert.equal(data.target, .15);
  assert.equal(data.payload, .5);
  assert.equal(data.height[2], .15);
  assert.equal(readMotion({ fixture, series: { ...series, time_s: [0, 1, 1, 2] } }), null);
  assert.equal(readMotion({ fixture, series: { ...series, position_m: [0, 0.1] } }), null);
});

test('robot paths and joint units come from the saved model, with a joint-only fallback', () => {
  const model = { tip_link: 'tool', joints: [{ name: 'lift', unit: 'm', child: 'carriage' }] };
  const trajectory = { time_s: [0, 1], tip_xyz_m: [[1, 0, 0], [1, 0, .25]], joint_positions: { lift: [0, .25] } };
  const data = readMotion({ model, trajectory });
  assert.equal(data.kind, 'robot');
  assert.deepEqual(data.joints[0], { name: 'lift', child: 'carriage', unit: 'm', values: [0, .25] });
  assert.equal(data.tipName, 'tool');
  assert.deepEqual(data.tip[1], [1, 0, .25]);
  assert.equal(readMotion({ model, trajectory: { ...trajectory, tip_xyz_m: [[0,0,0]] } }).tip, undefined);
});

test('link-frame geometry must match the active recording and resolves branched parents regardless of order', () => {
  const times = [0, .5];
  const root = { name: 'palm', parent: null, xyz_m: [[0,0,0], [0,0,0]] };
  const left = { name: 'left', parent: 'palm', xyz_m: [[1,0,0], [2,0,0]] };
  const right = { name: 'right', parent: 'palm', xyz_m: [[-1,0,0], [-2,0,0]] };
  const body = { root_link: 'palm', links: [left, root, right], time_s: times };
  assert.deepEqual(readLinks(body, times).map(link => link.parentIndex), [1, -1, 1]);
  assert.equal(readLinks(body, [0, 1]), null);
  assert.equal(readLinks({ ...body, links: [{ ...left, parent: 'missing' }, root] }, times), null);
  assert.equal(readLinks({ ...body, links: [root, { ...left, xyz_m: [[1,0,0], [2,0]] }] }, times), null);
  assert.deepEqual(projectPoint([1,2,3], 'XZ'), [1,3]);
});

test('joint response keeps measured and predicted signals distinct and opens held-out data first', () => {
  const fit = { time_s: [7, 8], position_rad: [0, .8], predicted_rad: [0, .75], command_rad: [1, 1] };
  const validation = { time_s: [2, 3], position_rad: [.2, .7], predicted_rad: [.1, .6] };
  const data = readMotion({ traces: { fit, validation } });
  assert.equal(data.kind, 'response');
  assert.deepEqual(data.logs.map(log => log.name), ['Held-out measurements', 'Training measurements']);
  assert.deepEqual(data.logs[0].measured, [.2,.7]);
  assert.deepEqual(data.logs[0].predicted, [.1,.6]);
  assert.equal(data.logs[0].command, undefined);
});

test('numeric time-series results get signal playback and spatial-only or malformed data stays static', () => {
  const data = readMotion({ traces: { time_s: [0, 0.5, 3], load_n: [0, 2, 2], missing: [], text: ['a','b','c'] } });
  assert.deepEqual(data.channels, [{ name: 'load_n', values: [0,2,2] }]);
  assert.equal(readMotion({ traces: { node_position_m: [0, 0.5], temperature_k: [290, 300] } }), null);
  assert.equal(readMotion({ series: { time_s: [0, NaN], force_n: [0,3] } }), null);
});
