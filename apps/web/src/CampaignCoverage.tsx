import { useEffect, useState } from 'react';
import { label, request } from './api';
import { Loading, Notice } from './components';
import type { OperatingFactor } from './projectTypes';

type Group = {
  adapter: string;
  counts: {planned: number; passed: number; failed: number; measurement_only: number; pending: number; blocked: number};
  grid: {planned_cells: number; observed_cells: number; possible_cells: number | null; unobserved_cells: number | null};
  factors: {field: string; label: string; unit: string; status: string; observed_values: number[];
    planned_values: number[]; isolated_pairs: number; verdict_changes: number}[];
  declared_factors: (OperatingFactor & {status: string; untested_values: number[] | null})[];
  conflicting_repeat_runs: string[];
  missing_combinations: Record<string,number>[];
};
const levels = (values: number[]) => values.length ? values.join(', ') : '—';

export function CampaignCoverage({projectId, batchId, status}: {projectId: string; batchId: string; status: string}) {
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<Group[]>();
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open) return;
    let current = true, timer = 0;
    async function load() {
      try {
        const path = '/project-campaigns/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(batchId) + '/coverage';
        const data = await request<{groups: Group[]}>(path);
        if (current) { setGroups(data.groups); setError(''); }
      } catch (e) { if (current) setError((e as Error).message); }
      if (current && status === 'running') timer = window.setTimeout(load, 3000);
    }
    void load();
    return () => { current = false; clearTimeout(timer); };
  }, [open, projectId, batchId, status, retry]);
  return <details className="compare-disclosure" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary>Operating-condition coverage</summary>
    {open && <div className="project-form-stack">
      {error && <Notice tone="error">{error} <button className="project-inline-button" onClick={() => setRetry(i => i+1)}>Retry</button></Notice>}
      {!error && !groups && <Loading/>}
      {groups?.map(group => <section key={group.adapter}><h4>{label(group.adapter)}</h4>
        <p>{group.counts.passed} passed · {group.counts.failed} failed · {group.counts.measurement_only} measurement only · {group.counts.pending} pending · {group.counts.blocked} without valid evidence</p>
        {group.conflicting_repeat_runs?.length > 0 && <Notice tone="warning">{group.conflicting_repeat_runs.length} runs have conflicting verdicts at repeated settings. These runs cannot establish which input changed the outcome.</Notice>}
        {group.grid.possible_cells !== null && <p><strong>{group.grid.observed_cells} of {group.grid.possible_cells} combinations observed</strong> across the listed campaign levels. Intermediate values and other deployment conditions require separate tests.</p>}
        {group.missing_combinations?.length > 0 && <details><summary>Show unobserved combinations ({group.missing_combinations.length} of {group.grid.unobserved_cells})</summary>
          <ul>{group.missing_combinations.map(point => <li key={JSON.stringify(point)}>{Object.entries(point).map(([field, value]) => {
            const factor = group.factors.find(f => f.field === field);
            return (factor?.label ?? label(field)) + ' ' + value + (factor?.unit ? ' ' + factor.unit : '');
          }).join(' · ')}</li>)}</ul></details>}
        {group.factors.length > 0 && <div className="analysis-table-scroll"><table className="data-table">
          <thead><tr><th>Model input</th><th>Observed levels</th><th>Coverage</th><th>One-input comparisons</th><th>Verdict changes</th></tr></thead>
          <tbody>{group.factors.map(f => <tr key={f.field}><td>{f.label} {f.unit && '(' + f.unit + ')'}</td>
            <td>{levels(f.observed_values)}</td><td>{label(f.status)}</td><td>{f.isolated_pairs}</td><td>{f.verdict_changes}</td></tr>)}</tbody>
        </table></div>}
        {group.declared_factors?.length ? <><h5>Declared site requirements</h5><div className="analysis-table-scroll"><table className="data-table">
          <thead><tr><th>Operating factor</th><th>Model evidence</th><th>Required levels</th><th>Missing levels</th></tr></thead>
          <tbody>{group.declared_factors.map(f => <tr key={f.name}><td>{f.name} {f.unit && '(' + f.unit + ')'}<small>{f.conditions}</small></td>
            <td>{label(f.status)}</td><td>{levels(f.required_values)}</td><td>{f.untested_values === null ? 'Check units' : f.required_values.length === 0 ? 'No levels specified' : f.untested_values.length ? levels(f.untested_values) : 'All listed levels observed'}</td></tr>)}</tbody>
        </table></div></> : <p>No site requirements were declared on this run revision. Add operating factors in the project’s Parameters tab before the next campaign.</p>}
      </section>)}
    </div>}
  </details>;
}
