import test from 'node:test';
import assert from 'node:assert/strict';
import { groupScenarioFamilies } from './scenarioFamilies.ts';

test('group shared mechanisms without merging runs or unverified hypotheses', () => {
  const card = (id, family_key = null, missing_capability = null) => ({ id, family_key, draft: { missing_capability } });
  const cards = [card('early', 'lift.press_timing'), card('missing-a'), card('late', 'lift.press_timing'),
    card('missing-b'), card('unmodeled', 'lift.press_timing', 'Needs contact dynamics')];
  const groups = groupScenarioFamilies(cards);
  assert.deepEqual(groups.map(group => group.candidates.map(item => item.id)), [
    ['early', 'late'], ['missing-a'], ['missing-b'], ['unmodeled'],
  ]);
  assert.equal(groups[0].title, 'Press timing');
});
