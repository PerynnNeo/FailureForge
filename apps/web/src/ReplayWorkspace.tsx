import { useEffect, useRef, useState } from 'react';
import { formatTime, label, request } from './api';
import { Icon, Loading, Notice, Status } from './components';
import type { RunDetail, RunSummary } from './analysisInputs';
import type { Condition } from './campaignCompare';
import { coordinateText, verdict } from './campaignVerdict';
import { CompareWithReference } from './CompareWithReference';
import { RunVisual } from './RunVisual';
import './replayWorkspace.css';

type Batch = {
  suite_id: string; kind: string; label: string; status: string; project_revision: number;
  runs: Condition[]; field?: string | null;
};
const active = (status: string) => status === 'running' || status === 'queued';

export default function ReplayWorkspace({ projectId, batchId, runId }: {
  projectId: string; batchId: string | null; runId: string | null;
}) {
  const base = '/projects/' + encodeURIComponent(projectId) + '/analysis';
  const [batch, setBatch] = useState<Batch | null>(null);
  const [history, setHistory] = useState<RunSummary[] | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [listError, setListError] = useState('');
  const [runError, setRunError] = useState('');
  const [retry, setRetry] = useState(0);
  const panel = useRef<HTMLElement>(null);
  const [metric, setMetric] = useState('');
  const [onlyFailures, setOnlyFailures] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  useEffect(() => {
    let current = true, timer = 0;
    async function load() {
      try {
        if (batchId) {
          const data = await request<Batch>(`/project-campaigns/${encodeURIComponent(projectId)}/${encodeURIComponent(batchId)}`);
          if (!current) return;
          setBatch(data);
          if (data.status === 'running') timer = window.setTimeout(load, 2000);
        } else {
          const data = await request<{ runs: RunSummary[] }>(base);
          if (!current) return;
          setHistory(data.runs);
          if (data.runs.some(row => active(row.status))) timer = window.setTimeout(load, 2000);
        }
        setListError('');
      } catch (error) { if (current) setListError((error as Error).message); }
    }
    void load();
    return () => { current = false; clearTimeout(timer); };
  }, [batchId, projectId, base, retry]);

  const selected = batchId
    ? runId ?? batch?.runs.find(row => row.passed === false && !row.error)?.id ?? batch?.runs[0]?.id
    : runId ?? history?.find(row => row.status === 'completed' && !row.reference_example)?.id ?? history?.[0]?.id;
  const valid = !batchId || batch?.runs.some(row => row.id === selected);
  const path = valid && selected ? base + '/' + encodeURIComponent(selected) : '';
  useEffect(() => {
    let current = true, timer = 0;
    setRun(null); setRunError('');
    async function load() {
      try {
        const data = await request<RunDetail>(path);
        if (current) {
          setRun(data);
          if (active(data.status)) timer = window.setTimeout(load, 2000);
        }
      } catch (error) { if (current) setRunError((error as Error).message); }
    }
    if (path) void load();
    return () => { current = false; clearTimeout(timer); };
  }, [path, retry]);

  const href = (id: string) => '#' + base + '?' + new URLSearchParams(batchId ? {batch: batchId, run: id} : {run: id});
  const metrics = [...new Set((batch?.runs ?? []).flatMap(row => Object.keys(row.metrics).filter(key => typeof row.metrics[key] === 'number')))];
  const key = metrics.includes(metric) ? metric : ['max_hold_error_m', 'continuous_peak_temperature_k', 'continuous_max_abs_displacement_m',
    'tip_sampled_path_length_m', 'validation_rmse_rad'].find(item => metrics.includes(item)) ?? metrics[0];
  const detail = run?.id === selected ? run : null;
  const reference = batch?.runs.find(row => row.reference);
  const failures = batch?.runs.filter(row => verdict(row) === 'Failed') ?? [];
  useEffect(() => {
    if (!batchId || !runId || detail?.id !== runId) return;
    const frame = requestAnimationFrame(() => panel.current?.scrollIntoView({block:'start'}));
    return () => cancelAnimationFrame(frame);
  }, [batchId, runId, detail?.id]);
  const error = listError || runError;
  const outcome = detail?.result?.passed ?? (detail?.result?.summary as Record<string, unknown> | undefined)?.validation_passed;
  function focusReplay() {
    requestAnimationFrame(() => { panel.current?.focus({preventScroll:true}); panel.current?.scrollIntoView({block:'start'}); });
  }
  return <div className="recorded-workspace">
    {error && <Notice tone="error">{error} <button type="button" className="project-inline-button" onClick={() => setRetry(i => i + 1)}>Retry</button></Notice>}
    {!error && (batchId ? !batch : !history) && <Loading/>}
    {batch && runId && !valid && <Notice tone="error">This run does not belong to the selected campaign.</Notice>}
    {!batchId && history?.length === 0 && !runId && <section className="project-empty"><h3>No recorded runs yet</h3><p>Run a supported analysis to record this project's first result.</p><a className="button primary" href={'#'+base}>Open Analysis &amp; runs</a></section>}
    {selected && valid && <section ref={panel} tabIndex={-1} className="project-panel recorded-result" aria-label="Visual result">
      <header className="project-panel-header recorded-heading"><div><h3>{detail?.label ?? 'Recorded result'}</h3>
        {detail && <p>{label(detail.adapter)} · Revision {detail.project_revision} · {formatTime(detail.created_at)}</p>}</div>
        {!batchId && history && (history.length > 1 || !history.some(row => row.id === selected)) && <label className="project-field"><span>Recorded run</span><select value={selected} onChange={e => { window.location.hash = href(e.target.value).slice(1); }}>
          {!history.some(row => row.id === selected) && <option value={selected}>{detail?.label ?? selected}</option>}
          {history.map(row => <option key={row.id} value={row.id}>{row.label} · rev {row.project_revision} · {row.id.slice(-6)}{row.reference_example ? ' · Reference hand example' : ''}</option>)}
        </select></label>}
      </header>
      <div className="project-form-stack">
        {detail ? <>
          <div className="analysis-actions"><Status value={detail.status}/>{detail.status === 'completed' &&
            <strong>{detail.assessment_error ? 'Inconclusive' : outcome === true ? 'Passed' : outcome === false ? 'Failed' : 'Measurement only'}</strong>}</div>
          {(detail.error || detail.assessment_error) && <Notice tone="warning">{detail.error || detail.assessment_error}</Notice>}
          <RunVisual run={detail} runPath={path}/>
          <details><summary>Recorded inputs and acceptance checks</summary><pre>{JSON.stringify({inputs:detail.inputs, criteria:detail.result?.criteria, summary:detail.result?.summary ?? detail.result?.metrics}, null, 2)}</pre></details>
          {detail.evidence_hash && <a className="button secondary" href={'/api'+path+'/bundle'} download><Icon name="download" size={16}/>Download evidence bundle</a>}
        </> : !runError && <Loading/>}
      </div>
    </section>}
    {batchId && batch && <section className="project-panel" aria-label="Campaign conditions">
      <header className="project-panel-header"><div><h3>{batch.label}</h3>
        <p>{batch.runs.length} conditions · Revision {batch.project_revision} · {batch.runs.filter(r => verdict(r) === 'Passed').length} passed · {failures.length} failed</p></div>
        <Status value={batch.status}/></header>
      <div className="project-form-stack">
        {reference && <p><strong>Reference condition</strong> <a className="text-link" href={href(reference.id)} onClick={focusReplay}>{coordinateText(reference, batch.field) || reference.label}</a> · {verdict(reference)}</p>}
        {batch.runs.filter(row => row.status === 'completed').length > 1 && <details className="compare-disclosure"
          onToggle={event => setCompareOpen(event.currentTarget.open)}>
          <summary>Compare with reference</summary>
          {compareOpen && <CompareWithReference key={selected} base={base} runs={batch.runs} field={batch.field}
            reference={reference} selectedId={selected}/>}
        </details>}
        {key && <label className="project-field"><span>Compare measured quantity</span><select value={key} onChange={e => setMetric(e.target.value)}>
          {metrics.map(k => <option key={k} value={k}>{label(k)}</option>)}</select></label>}
        {failures.length > 0 && <label className="recorded-filter"><input type="checkbox" checked={onlyFailures} onChange={e => setOnlyFailures(e.target.checked)}/>Show failed conditions only</label>}
        <div className="analysis-table-scroll"><table className="data-table"><thead><tr><th>Condition</th><th>Outcome</th>{key && <th>{label(key)}</th>}<th>Evidence</th></tr></thead>
          <tbody>{(onlyFailures && failures.length ? failures : batch.runs).map(row => <tr key={row.id} className={row.id === selected ? 'recorded-active' : ''}>
            <td>{row.label}<small>{coordinateText(row, batch.field)}{row.reference && ' · Reference'}</small></td>
            <td><strong className={row.passed === false ? 'text-red' : row.passed ? 'text-green' : undefined}>{verdict(row)}</strong>{row.error && <small>{row.error}</small>}</td>
            {key && <td>{typeof row.metrics[key] === 'number' ? Number(row.metrics[key].toPrecision(6)) : '—'}</td>}
            <td><a className="text-link" href={href(row.id)} onClick={focusReplay} aria-label={'View result for ' + row.label}>View result</a></td>
          </tr>)}</tbody></table></div>
      </div>
    </section>}
  </div>;
}
