import test from 'node:test';
import assert from 'node:assert/strict';
import { fieldText, inputFields, parseFields } from './analysisInputs.ts';
import { workerFor, workerLabel } from './workerStatus.ts';

test('analysis forms preserve nested data, numeric inputs and literal strings', () => {
  const model = {
    example: { component: '001', elements: 16, model: { kind: 'thermal_rod' }, fit: [{ measured: 0 }] },
    schema: { properties: {
      component: { type: 'string' }, elements: { type: 'integer' }, model: { oneOf: [{ $ref: '#/$defs/Thermal' }] },
      fit: { type: 'array' }, max_temperature_k: { anyOf: [{ type: 'number' }, { type: 'null' }] },
    }, required: ['component', 'elements', 'model', 'fit'] },
  };
  const fields = inputFields(model);
  const values = Object.fromEntries(Object.entries(model.example).map(([key, value]) => [key, fieldText(value)]));
  assert.deepEqual(parseFields(fields, values), model.example);
  assert.equal(parseFields(fields, { ...values, max_temperature_k: '352.1' }).max_temperature_k, 352.1);
  assert.equal(parseFields(fields, { ...values, max_temperature_k: '.05' }).max_temperature_k, 0.05);
  assert.throws(() => parseFields(fields, { ...values, elements: '2.5' }), /integer.*elements/);
  assert.throws(() => parseFields(fields, { ...values, component: '' }), /component/);
  assert.throws(() => parseFields(fields, { ...values, fit: '{}' }), /array.*fit/);
});

test('live eligibility and status use each campaign backend heartbeat', () => {
  const synthetic = { backend: 'synthetic', online: true, last_seen: 2 };
  const robot = { backend: 'libero', online: true, last_seen: 1 };
  const both = { worker: synthetic, workers: { synthetic, libero: robot } };
  assert.equal(workerFor(both, 'libero'), robot);
  assert.match(workerLabel(both), /Robot and synthetic/);
  assert.equal(workerFor({ worker: synthetic }, 'libero'), undefined);
  assert.equal(workerFor({ worker: robot }, 'libero'), robot);
});
