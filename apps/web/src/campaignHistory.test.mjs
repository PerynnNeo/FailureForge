import test from 'node:test';
import assert from 'node:assert/strict';
import { campaignHistory, filterCampaignHistory, projectBatchHref, projectCampaignSetup, readProjectBatches } from './campaignHistory.ts';

test('per-case evidence in a shared batch opens the measured variant', () => {
  assert.equal(projectBatchHref('p 1', 'suite/1', 'variant/3'), '#/projects/p%201/analysis?batch=suite%2F1&run=variant%2F3');
});

const batch = {
  suite_id: 'suite/1', project_id: 'project 1', project_name: 'Heat exchanger', project_revision: 3,
  label: 'Cooling range', kind: 'sweep', created_at: 1700000000, total: 4, completed: 2, status: 'running',
};
const benchmark = {
  id: 'bench/1', name: 'Dim lighting', backend: 'synthetic', created_at: '2023-11-14T22:15:00Z',
  budget: { completed: 8 }, episodes: [{ id: 'episode' }], status: 'completed',
};

test('campaign history links whole batches and benchmarks and keeps their progress units', () => {
  const rows = campaignHistory([batch], [benchmark]);
  assert.deepEqual(rows.map(row => [row.kind, row.href, row.progress]), [
    ['benchmark', '#/campaigns/bench%2F1', '8 episodes'],
    ['sweep', '#/projects/project%201/analysis?batch=suite%2F1', '2 / 4 runs'],
  ]);
  assert.equal(projectCampaignSetup('project 1'), '#/projects/project%201/analysis?setup=campaign');
  assert.deepEqual(filterCampaignHistory(rows, ' HEAT EXCHANGER ', 'active'), [rows[1]]);
  assert.deepEqual(filterCampaignHistory(rows, 'lighting', 'matrix'), []);
  assert.deepEqual(filterCampaignHistory(rows, 'bench/1', 'synthetic'), [rows[0]]);
});

test('campaign listing reads older project batches once even if pages overlap', async () => {
  const offsets = [];
  const items = await readProjectBatches(async (offset, limit) => {
    offsets.push(offset);
    assert.equal(limit, 200);
    return { total: 4, items: offset ? [batch, { ...batch, suite_id: 'suite/3' }] : [batch, { ...batch, suite_id: 'suite/2' }] };
  });
  assert.deepEqual(offsets, [0, 2]);
  assert.deepEqual(items.map(item => item.suite_id), ['suite/1', 'suite/2', 'suite/3']);
});
