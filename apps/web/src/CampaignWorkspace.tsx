import { useEffect, useState } from 'react';
import { formatTime, request } from './api';
import { Empty, Icon, Loading, Notice, SectionHeading, Status } from './components';
import { batchLabels, filterCampaignHistory, readProjectBatches } from './campaignHistory';
import type { CampaignRow, ProjectBatch } from './campaignHistory';
import { campaignListGuide } from './campaignTutorial';
import { HelpTutorial } from './HelpTutorial';
import './campaignWorkspace.css';

export function useProjectBatches(visible: boolean) {
  const [items, setItems] = useState<ProjectBatch[] | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!visible) return;
    let current = true;
    let loading = false;
    let timer = 0;
    async function load() {
      if (!current || loading || document.hidden) return;
      window.clearTimeout(timer);
      loading = true;
      try {
        const batches = await readProjectBatches((offset, limit) => request(`/project-campaigns?offset=${offset}&limit=${limit}`));
        if (current) {
          setItems(batches); setError('');
          if (batches.some(batch => batch.status === 'running')) timer = window.setTimeout(() => void load(), 4000);
        }
      } catch (failure) { if (current) setError((failure as Error).message); }
      finally { loading = false; }
    }
    const onVisibility = () => { if (!document.hidden) void load(); };
    void load();
    document.addEventListener('visibilitychange', onVisibility);
    return () => { current = false; window.clearTimeout(timer); document.removeEventListener('visibilitychange', onVisibility); };
  }, [visible, attempt]);
  return { items, error, retry: () => setAttempt(value => value + 1) };
}

export function NewCampaignLink() {
  return <a className="button primary" href="#/campaigns/new" data-tour="campaign-create"><Icon name="plus" size={18}/>New campaign</a>;
}

export function CampaignTable({ rows }: { rows: CampaignRow[] }) {
  return <div className="table-scroll"><table className="data-table campaign-table">
    <thead><tr><th>Campaign</th><th>Test type</th><th>Status</th><th>Completed</th><th>Created</th></tr></thead>
    <tbody>{rows.map((row, index) => <tr key={row.href}>
      <td><a className="row-title" data-tour={index === 0 ? 'campaign-open' : undefined} href={row.href}>{row.name}</a><small>{row.source}</small></td>
      <td>{batchLabels[row.kind]}</td><td><Status value={row.status}/></td><td>{row.progress}</td><td>{formatTime(row.created)}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function CampaignList({ rows, loading, error, retry, onBenchmark, benchmarkOpen }: {
  rows: CampaignRow[]; loading: boolean; error: string; retry: () => void; onBenchmark: () => void; benchmarkOpen: boolean;
}) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const filtered = filterCampaignHistory(rows, query, filter);
  return <>
    <SectionHeading title="Campaigns" description="Test a project across conditions, compare outcomes and inspect the recorded runs." action={<div className="analysis-actions">
      {!benchmarkOpen && <HelpTutorial title="Campaign tutorial" steps={campaignListGuide(filtered.length > 0)}/>}
      <button type="button" data-tour="campaign-benchmark" className="button secondary" onClick={onBenchmark}>New bowl benchmark</button>
      <NewCampaignLink/>
    </div>}/>
    <div className="list-toolbar">
      <div className="search-input"><Icon name="search" size={19}/><input data-tour="campaign-search" aria-label="Search campaigns"
        placeholder="Search by campaign, project or ID" value={query} onChange={event => setQuery(event.target.value)}/></div>
      <select data-tour="campaign-filter" aria-label="Filter campaigns" value={filter} onChange={event => setFilter(event.target.value)}>
        <option value="all">All campaigns</option><option value="active">Active campaigns</option>
        <option value="suite">Test suites</option><option value="sweep">Parameter sweeps</option><option value="matrix">Environment matrices</option>
        <option value="benchmark">All bowl benchmarks</option><option value="libero">LIBERO benchmarks</option><option value="synthetic">Synthetic validations</option>
      </select>
    </div>
    {error && <Notice tone="warning">{error} <button className="project-inline-button" onClick={retry}>Retry</button></Notice>}
    {loading && <Loading/>}
    {filtered.length ? <section className="card"><CampaignTable rows={filtered}/></section>
      : !loading && !error && <section className="card"><Empty title={rows.length ? 'No matching campaigns' : 'No campaigns yet'}>
        {rows.length ? 'Try another project name or filter.' : 'Choose New campaign to configure a batch of tests for a saved project.'}
      </Empty></section>}
  </>;
}
