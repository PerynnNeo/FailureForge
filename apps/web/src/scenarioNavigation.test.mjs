import test from 'node:test';
import assert from 'node:assert/strict';
import { scenarioGenerationHash, selectedScenarioBatch } from './scenarioNavigation.ts';

const batches = [{ id: 'recent' }, { id: 'older' }];
const query = hash => new URLSearchParams(hash.split('?')[1]);

test('switching saved batches builds a refreshable URL and retains unrelated route context', () => {
  const initial = 'tab=scenarios&example=shelf&reference=reference-1';
  const older = scenarioGenerationHash('test project', initial, 'older');
  assert.equal(older, '#/projects/test%20project?tab=scenarios&example=shelf&generation=older');
  const recent = scenarioGenerationHash('test project', query(older).toString(), 'recent');
  for (const [hash, batch] of [[older, batches[1]], [recent, batches[0]], [older, batches[1]]]) {
    assert.deepEqual(selectedScenarioBatch(batches, query(hash)), batch);
  }
});

test('reference links open setup even with saved batches, and a broken batch link never displays another result', () => {
  assert.equal(selectedScenarioBatch(batches, new URLSearchParams('tab=scenarios&reference=run')), undefined);
  assert.equal(selectedScenarioBatch(batches, new URLSearchParams('generation=missing')), undefined);
  assert.equal(selectedScenarioBatch(batches, new URLSearchParams('generation=older&reference=run')), batches[1]);
  assert.equal(selectedScenarioBatch(batches, new URLSearchParams('tab=scenarios')), batches[0]);
});
