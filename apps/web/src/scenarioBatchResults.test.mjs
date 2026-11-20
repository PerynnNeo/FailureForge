import test from 'node:test';
import assert from 'node:assert/strict';
import { coverageText, reportInProgress, verdictLabel } from './scenarioVerdicts.ts';

test('pending solver cases keep polling after generation completes; blocked cases are never assessed', () => {
  const report = { target: 5, generation_status: 'completed', counts: { proposed: 5, pending: 1, assessed: 2, submitted: 3, blocked: 2 } };
  assert.equal(reportInProgress(report), true);
  assert.equal(coverageText(report), '2 of 5 proposed cases assessed · Target 5 cases');
  assert.equal(reportInProgress({ ...report, counts: { ...report.counts, pending: 0 } }), false);
  assert.equal(coverageText({ ...report, target: null }), '2 of 3 submitted cases assessed');
  assert.equal(verdictLabel('invalid'), 'Invalid setup');
  assert.equal(verdictLabel('failed'), 'Failed');
  assert.equal(verdictLabel('inconclusive'), 'Inconclusive');
});
