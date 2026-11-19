import assert from 'node:assert/strict';
import test from 'node:test';
import { axisChoices, gridLevels } from './campaignAxes.ts';

test('grid options follow the current edited draft and expand concrete named joint commands', () => {
  const fields = [{field: 'targets.*', label: 'Joint', unit: 'joint units'}, {field: 'load', label: 'Load', unit: 'N'}];
  const choices = axisChoices(fields, {targets: '{"j.1": 0, "j2": 0.25}', load: '2'}, {load: 'Rated load'});
  assert.deepEqual(choices.map(x => x.field), ['targets.j.1', 'targets.j2']);
  assert.deepEqual(gridLevels('-2, 0, +2e0', choices[0], 8), [-2, 0, 2]);
  const [edited] = axisChoices(fields, {targets: '{"j.1": 1}'}, {});
  assert.throws(() => gridLevels('-2, 0, 2', edited, 8), /reference/);
  for (const levels of ['1', '1,1', '0, 0x1', '1, 0', 'NaN, 1', '0,1,2,3,4,5,6,7,8']) {
    assert.throws(() => gridLevels(levels, edited, 8));
  }
});
