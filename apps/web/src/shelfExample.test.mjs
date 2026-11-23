import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { findShelfSuite, savedShelfInputs, shelfReading, shelfTests } from './shelfExample.ts';

const { inputs } = JSON.parse(readFileSync(new URL('../public/examples/beam-reference.json', import.meta.url)));
const pair = shelfTests(inputs).map((run, i) => ({ ...run, id: String(i), suite_id: 'pair', project_revision: 1 }));

test('the guided pair moves the same total load and preserves the beam', () => {
  assert.equal(pair[1].inputs.tip_force_n, inputs.distributed_load_n_per_m * inputs.length_m);
  assert.deepEqual(savedShelfInputs(pair), inputs);
  assert.equal(findShelfSuite([pair[1], pair[0]]), 'pair');
  assert.equal(findShelfSuite([pair[0], { ...pair[1], suite_id: 'another' }]), undefined);
  assert.equal(savedShelfInputs([pair[0], { ...pair[1], inputs: { ...pair[1].inputs, width_m: 0.09 } }]), null);
});

test('a verdict requires completed, applicable solver evidence', () => {
  const run = { status: 'completed', evidence_hash: 'verified', result: { passed: false, acceptance_checks: [
    { quantity: 'continuous_max_abs_displacement_m', measured: 0.00011, maximum: 0.0001, passed: false }
  ] } };
  assert.deepEqual(shelfReading(run), { passed: false, mm: 0.11, limitMm: 0.1 });
  for (const invalid of [{ status: 'queued' }, { evidence_hash: null }, { assessment_error: 'Outside the model' }, { result: {} }]) {
    assert.equal(shelfReading({ ...run, ...invalid }), null);
  }
});
