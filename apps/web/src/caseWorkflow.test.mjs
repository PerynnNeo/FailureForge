import assert from 'node:assert/strict';
import test from 'node:test';
import { caseActionAvailability, collectCasePairs } from './caseWorkflow.ts';

test('requested reduction and confirmation allocations cannot be requested again', () => {
  const available = caseActionAvailability([
    { id: 'a', kind: 'reduce', status: 'interrupted' },
    { id: 'b', kind: 'confirm', status: 'succeeded' },
  ]);
  assert.equal(available.canReduce, false);
  assert.equal(available.canConfirm, false);
  assert.equal(available.canRerun, true);
});

test('active campaign work disables every additional case action', () => {
  for (const status of ['queued', 'running', 'cancelling']) {
    const available = caseActionAvailability([{ id: 'a', kind: 'rerun', status }]);
    assert.equal(available.canReduce, false);
    assert.equal(available.canConfirm, false);
    assert.equal(available.canRerun, false);
  }
});

test('pair deduplication preserves distinct original, reduction, confirmation and rerun executions', () => {
  const pair = (name, state_id = 0) => ({ state_id, reference_episode_id: `${name}-reference`, changed_episode_id: `${name}-changed` });
  const selected = pair('final');
  const result = collectCasePairs({
    pairs: [selected], reduction_final_pairs: [selected],
    search_pairs: [pair('search')], reduction_initial_pairs: [pair('initial')],
    confirmation_pairs: [pair('held-out', 2)], reruns: [{ pairs: [pair('rerun')] }],
  });
  assert.equal(result.length, 5);
  assert.deepEqual(result.map(entry => entry.changed_episode_id), ['final-changed', 'search-changed', 'initial-changed', 'held-out-changed', 'rerun-changed']);
  assert.equal(result[3].phase, 'held-out confirmation');
});
