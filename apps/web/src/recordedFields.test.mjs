import test from 'node:test';
import assert from 'node:assert/strict';
import { materialReadings, sectionValues, spatialField } from './recordedFields.ts';

test('beam sweep retains signed displacements and the correct element side at a node', () => {
  const beam = spatialField({ kind: 'structural_beam', traces: { node_position_m: [0, 0.05, 0.2],
    displacement_m: [0, -0.0002, -0.0004], rotation_rad: [0, -0.004, -0.005],
    element_left_surface_stress_pa: [6e6, 3e6], element_right_surface_stress_pa: [4e6, 0] } });
  assert.deepEqual(sectionValues(beam, 1).map(m => [m.value,m.unit]), [[0.05,'m'],[-0.2,'mm'],[-0.004,'rad'],[4,'MPa'],[3,'MPa']]);
  assert.equal(sectionValues(beam, 0).at(-1).label, 'Stress on right element');
  assert.equal(sectionValues(beam, 2).at(-1).label, 'Stress on left element');
});

test('rod field reports both adjacent fluxes and does not invent a boundary flux', () => {
  const rod = spatialField({ kind: 'thermal_rod', traces: { node_position_m: [0, 1, 3],
    temperature_k: [300, 330, 310], element_heat_flux_w_m2: [-20, 12] } });
  assert.deepEqual(sectionValues(rod, 1).map(m => m.value), [1,330,-20,12]);
  assert.deepEqual(sectionValues(rod, 2).map(m => m.value), [3,310,12]);
});

test('malformed spatial axes and incomplete field values are not replayed', () => {
  for (const [x, t] of [[[0], [310]], [[0,1],[300]], [[0,0],[300,300]], [[0,1],[null,290]]]) {
    assert.equal(spatialField({kind:'thermal_rod',traces:{node_position_m:x,temperature_k:t}}), null);
  }
  assert.deepEqual(spatialField({ kind:'thermal_rod', traces:{ node_position_m:[0,1], temperature_k:[301,301] } }).values,[301,301]);
});

test('calibration keeps independent samples, units and held-out tolerance separate', () => {
  const measured = { run_id: 'A', measured: 290, predicted: 291, residual: 1 };
  const data = materialReadings({kind:'calibration',summary:{residual_unit:'K',validation_tolerance:2},
    fit:[measured],validation:[{...measured,run_id:'B', residual:-1, predicted:289}, {run_id:'partial', measured:300}]});
  assert.equal(data.unit,'K');
  assert.equal(data.tolerance,2);
  assert.deepEqual(data.fit,[{id:'A', measured:290, predicted:291, residual:1}]);
  assert.deepEqual(data.validation,[{id:'B', measured:290, predicted:289, residual:-1}]);
  assert.equal(materialReadings({kind:'calibration',fit:[],validation:[]}),null);
});
