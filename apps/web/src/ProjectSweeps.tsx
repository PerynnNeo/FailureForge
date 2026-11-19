import { useEffect, useState } from 'react';
import { formatTime, label, post, request } from './api';
import { Notice, Status } from './components';
import type { RunInput } from './analysisInputs';
import { axisChoices, gridLevels } from './campaignAxes';
import type { AxisField } from './campaignAxes';

export type SweepCatalog = { adapters: Record<string, AxisField[]>; max_points: number };
type Sweep = { suite_id: string; label: string; adapter: string; field: string; reference_value: number; project_revision: number; created_at: string };
type Point = { value: number; reference: boolean; run_id: string; status: string; passed: boolean | null; error?: string; metrics: Record<string, unknown> };
type SweepDetail = Sweep & {
  status: string; reference_passed: boolean | null; nearest_observed_failure: Point | null; points: Point[];
  counts: { total: number; measured: number; passed: number; failed: number; pending: number; blocked: number; measurement_only: number };
};

export default function ProjectSweeps({ projectId, revision, adapter, draft, bindings, currentTest, disabled, onRun, onQueue, setupCatalog, onCreated }: {
  projectId: string; revision: number; adapter: string; draft: Record<string, string>; bindings: Record<string, string>;
  currentTest: () => RunInput; disabled: boolean; onRun: (id: string) => void; onQueue: () => void;
  setupCatalog?: SweepCatalog; onCreated?: (suiteId: string) => void;
}) {
  const base = `/projects/${encodeURIComponent(projectId)}/sweeps`;
  const [open, setOpen] = useState(false);
  const [savedCatalog, setCatalog] = useState<SweepCatalog | null>(null);
  const catalog = setupCatalog ?? savedCatalog;
  const [sweeps, setSweeps] = useState<Sweep[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState<SweepDetail | null>(null);
  const [selectedField, setSelectedField] = useState('');
  const [values, setValues] = useState('');
  const [metric, setMetric] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [submission, setSubmission] = useState<{ body: string; key: string } | null>(null);
  const fields = axisChoices(catalog?.adapters[adapter] ?? [], draft, bindings);
  const selected = fields.find(item => item.field === selectedField) ?? fields[0];
  const sweep = sweeps.find(item => item.suite_id === selectedId) ?? sweeps[0];
  const metrics = [...new Set((detail?.points ?? []).flatMap(point => Object.keys(point.metrics ?? {})
    .filter(key => typeof point.metrics[key] === 'number')))];
  const preferred = ['continuous_peak_temperature_k', 'continuous_max_abs_displacement_m', 'tip_displacement_m'];
  const shownMetric = metrics.includes(metric) ? metric : preferred.find(key => metrics.includes(key)) ?? metrics[0];
  useEffect(() => { setValues(''); setError(''); }, [adapter, selected?.field]);
  useEffect(() => {
    let current = true;
    if (open && !setupCatalog) void Promise.all([request<SweepCatalog>(`${base}/catalog`), request<{ sweeps: Sweep[] }>(base)])
      .then(([options, history]) => { if (current) { setCatalog(options); setSweeps(history.sweeps); setLoadError(''); } })
      .catch((failure: Error) => { if (current) setLoadError(failure.message); });
    return () => { current = false; };
  }, [open, base, revision, refresh, setupCatalog]);
  useEffect(() => {
    if (!open || !sweep) return;
    let current = true;
    let timer = 0;
    async function load() {
      try {
        const item = await request<SweepDetail>(`${base}/${encodeURIComponent(sweep!.suite_id)}`);
        if (current) {
          setDetail(item); setLoadError('');
          if (item.counts.pending) timer = window.setTimeout(() => void load(), 2500);
        }
      } catch (failure) { if (current) setLoadError((failure as Error).message); }
    }
    void load();
    return () => { current = false; window.clearTimeout(timer); };
  }, [open, base, sweep?.suite_id, refresh]);
  async function runSweep() {
    if (!selected || !catalog || disabled || working) return;
    setWorking(true); setError('');
    try {
      const points = gridLevels(values, selected, catalog.max_points);
      const body = { expected_revision: revision, ...currentTest(), field: selected.field, values: points };
      const encoded = JSON.stringify(body);
      const key = submission?.body === encoded ? submission.key : crypto.randomUUID();
      setSubmission({ body: encoded, key });
      const result = await post<SweepDetail>(base, body, key);
      if (onCreated) { setSubmission(null); onCreated(result.suite_id); return; }
      setSelectedId(result.suite_id); setDetail(result); setSubmission(null);
      setRefresh(index => index + 1); onQueue();
    } catch (failure) { setError((failure as Error).message); }
    finally { setWorking(false); }
  }
  const controls = <div className="project-form-stack">
      {loadError && <Notice tone="error">{loadError} <button type="button" className="project-inline-button" onClick={() => setRefresh(index => index + 1)}>Retry</button></Notice>}
      {catalog && (selected ? <>
        <label className="project-field"><span>Vary one input</span><select aria-label="Sweep field" value={selected.field}
          onChange={event => { setSelectedField(event.target.value); setValues(''); }}>
          {fields.map(item => <option key={item.field} value={item.field}>{item.label} ({item.unit})</option>)}
        </select></label>
        <label className="project-field" data-tour="campaign-sweep-values"><span>Values in increasing order ({selected.unit})</span>
          <input value={values} onChange={event => setValues(event.target.value)} placeholder="Separate values with commas"/>
          <small>Include the reference value {selected.value}. Each of the 2–{catalog.max_points} points uses the run label and other inputs above.</small>
        </label>
        <button className="button primary" type="button" disabled={disabled || working || !values.trim()} onClick={() => void runSweep()}>{working ? 'Queuing…' : 'Run sweep'}</button>
      </> : <p className="small muted">This model has no sweepable numeric inputs configured.</p>)}
      {error && <Notice tone="error">{error}</Notice>}
      {sweeps.length > 0 && <label className="project-field"><span>Recorded sweep</span><select value={sweep.suite_id} onChange={event => { setSelectedId(event.target.value); setMetric(''); }}>
        {sweeps.map(item => <option key={item.suite_id} value={item.suite_id}>{item.label} · {item.field} · rev {item.project_revision} · {formatTime(item.created_at)}</option>)}
      </select></label>}
      {detail && detail.suite_id === sweep?.suite_id && <>
        <div className="analysis-actions"><Status value={detail.status}/><span>{detail.counts.measured} / {detail.counts.total} measured</span></div>
        <p className="small">Passed {detail.counts.passed} · Failed {detail.counts.failed} · Measurement only {detail.counts.measurement_only} · Pending {detail.counts.pending} · Blocked {detail.counts.blocked}</p>
        {detail.nearest_observed_failure && <p>Nearest observed failure to reference {detail.reference_value} occurred at <strong>{detail.nearest_observed_failure.value}</strong>.</p>}
        {shownMetric && <label className="project-field"><span>Measured quantity</span><select value={shownMetric} onChange={event => setMetric(event.target.value)}>
          {metrics.map(key => <option value={key} key={key}>{label(key)}</option>)}
        </select></label>}
        <div className="analysis-table-scroll"><table className="data-table"><thead><tr><th>{label(detail.field)}</th>{shownMetric && <th>{label(shownMetric)}</th>}<th>Run</th><th>Acceptance</th><th>Evidence</th></tr></thead>
          <tbody>{detail.points.map(point => <tr key={point.run_id}><td>{point.value}{point.reference && ' (reference)'}</td>
            {shownMetric && <td>{typeof point.metrics?.[shownMetric] === 'number' ? Number(point.metrics[shownMetric].toPrecision(7)) : '—'}</td>}
            <td><Status value={point.status}/></td>
            <td>{point.error ? 'Blocked' : point.passed == null ? point.status === 'completed' ? 'Measurement only' : '—' : point.passed ? 'Passed' : 'Failed'}
              {point.error && <small className="sweep-point-error">{point.error}</small>}</td>
            <td><button type="button" className="project-inline-button" onClick={() => onRun(point.run_id)}>Inspect run</button></td></tr>)}</tbody></table></div>
        <a className="button secondary" href={`/api${base}/${encodeURIComponent(detail.suite_id)}`} download={`${detail.suite_id}-sweep.json`}>Export sweep JSON</a>
      </>}
    </div>;
  if (setupCatalog) return <section className="project-panel" data-tour="campaign-sweep"><header className="project-panel-header"><h3>Sweep values</h3></header>{controls}</section>;
  return <details className="project-panel sweep-panel" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Parameter sweeps</summary>{open && controls}
  </details>;
}
