import type { Backend, Campaign } from './types';

export type ProjectBatch = {
  suite_id: string; project_id: string; project_name: string; project_revision: number;
  kind: 'suite' | 'sweep' | 'matrix'; label: string; created_at: string | number;
  status: 'completed' | 'running' | 'partial'; total: number; completed: number;
};
type ProjectBatchPage = { items: ProjectBatch[]; total: number };

export const batchLabels = { suite: 'Test suite', sweep: 'Parameter sweep', matrix: 'Environment matrix', benchmark: 'Bowl benchmark' };
export type CampaignRow = {
  id: string; name: string; kind: keyof typeof batchLabels; source: string; status: string;
  created: string | number; progress: string; href: string; backend?: Backend;
};
export const activeCampaignStatus = (status: string) =>
  ['queued', 'running', 'searching', 'reducing', 'confirming', 'pending', 'cancelling'].includes(status);

export const projectCampaignSetup = (projectId: string) => `#/projects/${encodeURIComponent(projectId)}/analysis?setup=campaign`;
export const projectBatchHref = (projectId: string, suiteId: string, runId?: string | null) =>
  `#/projects/${encodeURIComponent(projectId)}/analysis?batch=${encodeURIComponent(suiteId)}` +
  (runId ? '&run=' + encodeURIComponent(runId) : '');

export async function readProjectBatches(fetchPage: (offset: number, limit: number) => Promise<ProjectBatchPage>) {
  const batches = new Map<string, ProjectBatch>();
  let offset = 0;
  let total: number;
  do {
    const page = await fetchPage(offset, 200);
    total = page.total;
    for (const item of page.items) batches.set(projectBatchHref(item.project_id, item.suite_id), item);
    if (!page.items.length) break;
    offset += page.items.length;
  } while (offset < total);
  return [...batches.values()];
}

function timestamp(value: string | number) {
  return typeof value === 'number' ? value * 1000 : Date.parse(value);
}

export function campaignHistory(projects: ProjectBatch[], benchmarks: Campaign[]): CampaignRow[] {
  const rows: CampaignRow[] = projects.map(batch => ({
    id: batch.suite_id, name: batch.label, kind: batch.kind,
    source: `${batch.project_name} · revision ${batch.project_revision}`,
    status: batch.status, created: batch.created_at,
    progress: `${batch.completed} / ${batch.total} runs`,
    href: projectBatchHref(batch.project_id, batch.suite_id),
  }));
  for (const item of benchmarks) {
    const completed = item.budget?.completed ?? 0;
    rows.push({
      id: item.id, name: item.name, kind: 'benchmark', backend: item.backend,
      source: item.backend === 'libero' ? 'LIBERO robot experiment' : 'Synthetic validation',
      status: item.status, created: item.created_at, progress: `${completed} ${completed === 1 ? 'episode' : 'episodes'}`,
      href: `#/campaigns/${encodeURIComponent(item.id)}`,
    });
  }
  return rows.sort((a, b) => timestamp(b.created) - timestamp(a.created) || a.href.localeCompare(b.href));
}

export function filterCampaignHistory(rows: CampaignRow[], query: string, filter: string) {
  const search = query.trim().toLowerCase();
  return rows.filter(row => {
    const match = `${row.name} ${row.source} ${row.id} ${batchLabels[row.kind]}`.toLowerCase().includes(search);
    return match && (filter === 'all' || filter === row.kind || filter === row.backend ||
      (filter === 'active' && activeCampaignStatus(row.status)));
  });
}
