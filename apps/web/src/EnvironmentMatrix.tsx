import { useEffect, useRef, useState } from 'react';
import { formatTime, label, post, request } from './api';
import { LiftTrace } from './AnalysisResults';
import { Loading, Notice } from './components';
import { axisValues, cellOutcome, millimetres } from './environmentConditions';
import type { MatrixCell, MatrixDetail, MatrixRecord } from './environmentConditions';
import type { Inputs, RunDetail } from './analysisInputs';

const describeError = (error: unknown) => error instanceof Error ? error.message : 'The request failed.';
const formatRun = (matrix: MatrixRecord) => `${matrix.label} · revision ${matrix.project_revision} · ${formatTime(matrix.created_at)}`;

function Condition({ cell, projectId, back }: { cell: MatrixCell; projectId: string; back: () => void }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const path = `/projects/${encodeURIComponent(projectId)}/analysis/${encodeURIComponent(cell.run_id!)}`;
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, []);
  useEffect(() => {
    let current = true;
    void request<RunDetail>(path).then(record => {
      if (current) { setRun(record); setError(''); }
    }).catch(failure => { if (current) setError(describeError(failure)); });
    return () => { current = false; };
  }, [path, cell.status, attempt]);
  const metrics = run?.result?.summary as Inputs | undefined;
  const criteria = run?.result?.criteria as Inputs | undefined;
  const outcome = cellOutcome(cell);
  return <section className="matrix-condition" data-tour="project-matrix">
    <button type="button" className="project-inline-button" onClick={back}>← Back to matrix</button>
    <h4 tabIndex={-1} ref={heading}>{cell.payload_kg} kg payload · {cell.head_force_n} N head force</h4>
    <div className="matrix-counts"><strong className={`matrix-tag ${outcome.toLowerCase()}`}>{outcome}</strong>
      {cell.reference && <span>Reference condition</span>}</div>
    {cell.error && <Notice tone="warning">{cell.error}</Notice>}
    {error ? <Notice tone="error">{error} <button type="button" className="project-inline-button" onClick={() => setAttempt(n => n + 1)}>Retry</button></Notice>
      : !run ? <Loading/> : <>
        {metrics && <dl className="analysis-metrics">
          <div><dt>Error at arrival</dt><dd>{millimetres(metrics.arrival_error_m)}</dd></div>
          <div><dt>Maximum error during hold</dt><dd>{millimetres(metrics.max_hold_error_m)}</dd></div>
          <div><dt>Allowed error</dt><dd>{millimetres(metrics.error_limit_m)}</dd></div>
        </dl>}
        {criteria && <ul className="matrix-checks">{Object.entries(criteria).filter(([, v]) => typeof v === 'boolean').map(([key, passed]) => {
          const name = ({ arrived_within_tolerance: 'Arrival height', held_within_tolerance: 'Hold height',
            stayed_within_travel: 'Carriage travel', stayed_within_speed_limit: 'Speed limit' } as Record<string, string>)[key] ?? label(key);
          return <li key={key}>{name}<strong className={`matrix-tag ${passed ? 'passed' : 'failed'}`}>{passed ? 'Passed' : 'Failed'}</strong></li>;
        })}</ul>}
        {run.result && <LiftTrace result={run.result}/>}
        <div className="analysis-actions">
          <a className="button secondary" href={`/api${path}`} download={`${run.id}.json`}>Export run JSON</a>
          {cell.bundle_url && <a className="button secondary" href={cell.bundle_url} download={`${run.id}.zip`}>Download evidence bundle</a>}
        </div>
      </>}
  </section>;
}

function MatrixForm({ revision, disabled, base, onSaved, tour }: {
  revision: number; disabled: boolean; base: string; onSaved: (result: MatrixDetail) => void; tour?: string;
}) {
  const [name, setName] = useState('Packaging station loads');
  const [payload, setPayload] = useState('0, 0.25, 0.5');
  const [force, setForce] = useState('0, 1, 2');
  const [payloadRef, setPayloadRef] = useState('0');
  const [forceRef, setForceRef] = useState('0');
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const submission = useRef<{ body: string; key: string } | null>(null);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (disabled || working) return;
    setError(''); setWorking(true);
    try {
      const payloads = axisValues(payload, 'payload'), forces = axisValues(force, 'head force');
      if (payloads.length * forces.length > 16) throw new Error('A matrix can include up to 16 combinations.');
      if (!payloadRef.trim() || !forceRef.trim() || !payloads.includes(Number(payloadRef)) || !forces.includes(Number(forceRef))) {
        throw new Error('Include the reference payload and head force in their respective axis values.');
      }
      const body = { adapter: 'packaging_lift', label: name.trim(), expected_revision: revision,
        payload_kg: payloads, head_force_n: forces, reference: { payload_kg: Number(payloadRef), head_force_n: Number(forceRef) } };
      const encoded = JSON.stringify(body);
      if (submission.current?.body !== encoded) submission.current = { body: encoded, key: crypto.randomUUID() };
      const result = await post<MatrixDetail>(base, body, submission.current.key);
      submission.current = null; onSaved(result);
    } catch (failure) { setError(describeError(failure)); }
    finally { setWorking(false); }
  }
  return <form onSubmit={submit} className="matrix-form"><fieldset disabled={disabled || working}>
    <label className="project-field"><span>Matrix name</span><input required maxLength={100} value={name} onChange={e => setName(e.target.value)}/></label>
    <div className="project-form-grid" data-tour={tour}>
      <label className="project-field"><span>Parcel masses (kg)</span><input required value={payload} onChange={e => setPayload(e.target.value)}/></label>
      <label className="project-field"><span>Downward head forces (N)</span><input required value={force} onChange={e => setForce(e.target.value)}/></label>
    </div>
    <p className="small muted">Enter increasing values separated by commas. Each mass is tested with each force, up to 16 combinations.</p>
    <div className="project-form-grid">
      <label className="project-field"><span>Reference parcel (kg)</span><input required type="number" min="0" step="any" value={payloadRef} onChange={e => setPayloadRef(e.target.value)}/></label>
      <label className="project-field"><span>Reference head force (N)</span><input required type="number" min="0" step="any" value={forceRef} onChange={e => setForceRef(e.target.value)}/></label>
    </div>
    <button type="submit" className="button primary">{working ? 'Queuing…' : 'Run environment matrix'}</button>
  </fieldset>{error && <Notice tone="error">{error}</Notice>}</form>;
}

export default function EnvironmentMatrix({ projectId, revision, available, disabled, onQueue, revealRequest, onVisibilityChange }: {
  projectId: string; revision: number; available: boolean; disabled: boolean; onQueue: () => void; revealRequest: number;
  onVisibilityChange: (visible: boolean) => void;
}) {
  const base = `/projects/${encodeURIComponent(projectId)}/environment-matrices`;
  const [records, setRecords] = useState<MatrixRecord[] | null>(null);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<MatrixDetail | null>(null);
  const [inspected, setInspected] = useState('');
  const [error, setError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState(false);
  const activeId = selected || records?.[0]?.suite_id;
  const heading = useRef<HTMLHeadingElement>(null);
  const lastReveal = useRef(0);
  const showPanel = available || !!records?.length;
  useEffect(() => { onVisibilityChange(showPanel); }, [showPanel, onVisibilityChange]);
  useEffect(() => {
    if (!showPanel || !revealRequest || lastReveal.current === revealRequest) return;
    const frame = requestAnimationFrame(() => {
      lastReveal.current = revealRequest;
      setInspected('');
      heading.current?.focus({ preventScroll: true });
      heading.current?.scrollIntoView({ block: 'start' });
    });
    return () => cancelAnimationFrame(frame);
  }, [showPanel, revealRequest]);
  useEffect(() => {
    let current = true;
    void request<{ matrices: MatrixRecord[] }>(base).then(({ matrices }) => {
      if (current) { setRecords(matrices); setError(''); }
    }).catch(failure => { if (current) setError(describeError(failure)); });
    return () => { current = false; };
  }, [base, revision, refresh]);
  useEffect(() => {
    if (!activeId) return;
    let current = true, timer = 0;
    async function load() {
      try {
        const data = await request<MatrixDetail>(`${base}/${encodeURIComponent(activeId!)}`);
        if (current) {
          setDetail(data); setDetailError('');
          if (data.counts.pending) timer = window.setTimeout(() => void load(), 2000);
        }
      } catch (failure) { if (current) setDetailError(describeError(failure)); }
    }
    void load();
    return () => { current = false; window.clearTimeout(timer); };
  }, [activeId, base, refresh]);
  const matrix = detail?.suite_id === activeId ? detail : null;
  const condition = matrix?.cells.find(cell => cell.run_id && cell.run_id === inspected);
  function saved(data: MatrixDetail) {
    setEditing(false); setInspected(''); setRecords(prev => [data, ...(prev ?? []).filter(record => record.suite_id !== data.suite_id)]);
    setSelected(data.suite_id); setDetail(data); setRefresh(n => n + 1); onQueue();
  }
  if (!showPanel) return null;
  return <section className="project-panel environment-matrix" aria-label="Operating environment matrix">
    <header className="project-panel-header" data-tour={!matrix && (!records || activeId) ? 'project-matrix' : undefined}>
      <div><h3 ref={heading} tabIndex={-1} className="lift-matrix-heading">Operating environment matrix</h3>
      <p>The same packaging lift raises each parcel to 150 mm by 1 s, then holds it while the packing head presses down until 2 s. Arrival and hold must stay within 10 mm of target.</p>
    </div></header>
    <div className="project-form-stack">
      {(error || detailError) && <Notice tone="error">{error || detailError} <button type="button" className="project-inline-button" onClick={() => setRefresh(n => n + 1)}>Retry</button></Notice>}
      {!records && !error && <Loading/>}
      {records && records.length > 1 && <label className="project-field"><span>Recorded matrix</span>
        <select value={activeId} onChange={e => { setInspected(''); setSelected(e.target.value); setDetailError(''); }}>
          {records.map(record => <option key={record.suite_id} value={record.suite_id}>{formatRun(record)}</option>)}
        </select></label>}
      {activeId && !matrix && !detailError && <Loading/>}
      {matrix && (condition ? <Condition key={condition.run_id} cell={condition} projectId={projectId} back={() => {
        setInspected(''); window.requestAnimationFrame(() => document.getElementById(`condition-${condition.run_id}`)?.focus());
      }}/> : <>
        <div><h4>{matrix.label}</h4><p className="small muted">Revision {matrix.project_revision} · {formatTime(matrix.created_at)} · Simulation</p></div>
        <div className="matrix-counts" aria-live="polite"><strong>{matrix.counts.total} conditions</strong>
          <span className="matrix-tag passed">{matrix.counts.passed} passed</span>
          <span className="matrix-tag failed">{matrix.counts.failed} failed</span>
          {matrix.counts.pending > 0 && <span>{matrix.counts.pending} pending</span>}
          {matrix.counts.blocked > 0 && <span>{matrix.counts.blocked} blocked</span>}
        </div>
        <div className="matrix-table-scroll" data-tour="project-matrix"><table className="matrix-table">
          <caption>Maximum height error during the hold. Select a condition for its trajectory and checks.</caption>
          <thead><tr><th scope="col" rowSpan={2}>Parcel mass</th><th scope="colgroup" colSpan={matrix.head_force_n.length}>Downward head force</th></tr>
            <tr>{matrix.head_force_n.map(force => <th scope="col" key={force}>{force} N</th>)}</tr></thead>
          <tbody>{matrix.payload_kg.map(payload => <tr key={payload}><th scope="row">{payload} kg</th>{matrix.head_force_n.map(force => {
            const cell = matrix.cells.find(item => item.payload_kg === payload && item.head_force_n === force), outcome = cellOutcome(cell);
            return <td key={force}><button type="button" id={cell?.run_id ? `condition-${cell.run_id}` : undefined}
              disabled={!cell?.run_id} className={`matrix-cell ${outcome.toLowerCase()}`}
              aria-label={`Inspect ${payload} kg payload at ${force} N, ${outcome}${cell?.reference ? ', reference' : ''}`}
              onClick={() => cell?.run_id && setInspected(cell.run_id)}>
              <strong>{outcome}</strong>
              {(outcome === 'Passed' || outcome === 'Failed') && <span>{millimetres(cell?.metrics?.max_hold_error_m)}</span>}
              {cell?.reference && <small>Reference</small>}
            </button></td>;
          })}</tr>)}</tbody>
        </table></div>
        <div className="analysis-actions"><a className="button secondary" href={`/api${base}/${encodeURIComponent(matrix.suite_id)}`} download={`${matrix.suite_id}.json`}>Export matrix JSON</a>
          {available && <button className="button secondary" type="button" aria-expanded={editing} onClick={() => setEditing(!editing)}>
            {editing ? 'Close matrix setup' : 'New matrix'}</button>}</div>
      </>)}
      {available && records && (records.length === 0 || (editing && !condition)) && <MatrixForm base={base} disabled={disabled}
        revision={revision} onSaved={saved} tour={records.length === 0 ? 'project-matrix' : undefined}/>}
    </div>
  </section>;
}
