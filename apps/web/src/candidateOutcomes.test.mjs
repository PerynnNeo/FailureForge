import assert from 'node:assert/strict';
import test from 'node:test';
import { candidateFailureCount } from './candidateOutcomes.ts';

test('a complete two-state candidate reports integer failure counts from API fractions', () => {
  const candidate = { status: 'completed' };
  assert.equal(candidateFailureCount({ ...candidate, score: 0 }), 0);
  assert.equal(candidateFailureCount({ ...candidate, score: 0.5 }), 1);
  assert.equal(candidateFailureCount({ ...candidate, score: 1 }), 2);
});

test('incomplete or invalid pair scores are never presented as valid outcomes', () => {
  assert.equal(candidateFailureCount({ status: 'proposed', score: 0.5 }), null);
  assert.equal(candidateFailureCount({ status: 'completed', score: null }), null);
  assert.equal(candidateFailureCount({ status: 'completed', score: 0.25 }), null);
});
