import test from 'node:test';
import assert from 'node:assert/strict';
import { fieldCaption, fieldText, inputFields, motionModelChoice, parseFields, referenceHandChoice, rodBoundaryFields, runInputs } from './analysisInputs.ts';
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

test('thermal boundary options restore literal or bound fluid conditions and keep the inactive fields out of the run', () => {
  assert.deepEqual(rodBoundaryFields({right_temperature_k: '300'}, {}).required, ['right_temperature_k']);
  assert.equal(rodBoundaryFields({right_film_coefficient_w_m2k: '0'}, {}).fluid, true);
  assert.equal(rodBoundaryFields({}, {right_ambient_temperature_k: 'Measured air'}).fluid, true);
  const draft = {rightBoundaryChoice: 'fixed', right_temperature_k: '280', right_ambient_temperature_k: '320', right_film_coefficient_w_m2k: '70'};
  const schema = {type: 'number'};
  const fields = Object.keys(draft).filter(k => k !== 'rightBoundaryChoice').map(name => ({name, type:'number', schema}));
  const active = choice => fields.filter(field => !rodBoundaryFields({...draft, rightBoundaryChoice:choice}, {}).hidden.includes(field.name));
  assert.deepEqual(runInputs('thermal_rod', active('fixed'), draft), {right_temperature_k:280});
  assert.deepEqual(runInputs('thermal_rod', active('fluid'), draft), {right_ambient_temperature_k:320, right_film_coefficient_w_m2k:70});
  assert.match(fieldCaption(fields[2]), /W\/\(m²·K\)/);
});

test('motion drafts require a deliberate robot and preserve authored reference and URDF choices', () => {
  const fields = [{ name: 'model_asset_id', type: 'string', required: false }];
  assert.equal(motionModelChoice(undefined, false), '');
  assert.equal(motionModelChoice(undefined, true), referenceHandChoice);
  assert.equal(motionModelChoice({}, false), referenceHandChoice);
  assert.equal(motionModelChoice({ model_asset_id: 'asset_urdf' }, false), 'asset_urdf');
  assert.throws(() => runInputs('robot_motion', fields, {}), /Choose an attached URDF/);
  assert.deepEqual(runInputs('robot_motion', fields, { model_asset_id: referenceHandChoice }), {});
  assert.deepEqual(runInputs('robot_motion', fields, { model_asset_id: 'asset_urdf' }), { model_asset_id: 'asset_urdf' });
});
