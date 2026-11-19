import { useEffect, useState } from 'react';
import { formatTime, label, request } from './api';
import { Loading, Notice, Status } from './components';
import { TraceChart } from './Charts';
import MeshPreview from './MeshPreview';
import type { Adapter, Inputs, RunDetail, RunSummary } from './analysisInputs';

function scalar(value: unknown) {
  if (value === null) return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return Number(value.toPrecision(7)).toString();
  return String(value);
}

function Values({ values, inconclusive = false }: { values: Inputs; inconclusive?: boolean }) {
  const entries = Object.entries(values);
  const simple = entries.filter(([, value]) => value === null || typeof value !== 'object');
  const groups = entries.filter(([, value]) => value !== null && typeof value === 'object');
  return <>
    {simple.length > 0 && <dl className="analysis-metrics">{simple.map(([key, value]) =>
      <div key={key}><dt>{label(key)}</dt><dd>{inconclusive && key === 'passed' ? 'Inconclusive' :
        typeof value === 'string' && ['outcome', 'status', 'kind'].includes(key) ? label(value) : scalar(value)}</dd></div>)}</dl>}
    {groups.map(([key, value]) => {
      if (Array.isArray(value)) {
        if (!value.length) return null;
        if (value.every(item => typeof item === 'string')) {
          return <div className="analysis-notes" key={key}><h4>{label(key)}</h4><ul>{value.map((item, i) => <li key={i}>{item}</li>)}</ul></div>;
        }
        if (value.every(item => item && typeof item === 'object' && !Array.isArray(item) &&
          Object.values(item).every(v => v === null || typeof v !== 'object'))) {
          const columns = [...new Set(value.flatMap(row => Object.keys(row)))];
          return <details className="analysis-disclosure" key={key} open={key === 'validation' || key === 'acceptance_checks'}>
            <summary>{label(key)} ({value.length})</summary><div className="analysis-table-scroll"><table className="data-table">
              <thead><tr>{columns.map(column => <th key={column}>{label(column)}</th>)}</tr></thead>
              <tbody>{value.map((row, index) => <tr key={index}>{columns.map(column => <td key={column}>{scalar(row[column] ?? null)}</td>)}</tr>)}</tbody>
            </table></div></details>;
        }
        return <details className="analysis-disclosure" key={key}><summary>{label(key)} ({value.length})</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
      }
      return <details className="analysis-disclosure" key={key} open={['summary', 'metrics', 'changed_inputs', 'metric_deltas'].includes(key)}>
        <summary>{label(key)}</summary><Values values={value as Inputs} inconclusive={inconclusive && key === 'summary'}/>
      </details>;
    })}
  </>;
}

function FieldPlot({ result }: { result: Inputs }) {
  const [selectedJoint, setSelectedJoint] = useState('');
  const traces = result.traces as Inputs | undefined;
  if (Array.isArray(result.preview_triangles_m)) {
    const summary = result.summary as Inputs | undefined;
    return <MeshPreview triangles={result.preview_triangles_m} total={Number(summary?.triangles ?? result.preview_triangles_m.length)}/>;
  }
  const trajectory = result.trajectory as Inputs | undefined;
  if (trajectory && Array.isArray(trajectory.time_s) && trajectory.joint_positions) {
    const joints = trajectory.joint_positions as Record<string, number[]>;
    const names = Object.keys(joints);
    const joint = names.includes(selectedJoint) ? selectedJoint : names[0];
    if (!joint || !Array.isArray(joints[joint])) return null;
    const model = result.model as { joints?: Array<{ name: string; unit: string }> } | undefined;
    const unit = model?.joints?.find(item => item.name === joint)?.unit ?? '';
    const series = unit ? `position (${unit})` : 'position';
    const samples = trajectory.time_s.map((step, index) => ({ step, [series]: joints[joint][index] }));
    return <section><label className="project-field"><span>Joint trajectory</span>
      <select value={joint} onChange={event => setSelectedJoint(event.target.value)}>{names.map(name => <option key={name}>{name}</option>)}</select>
    </label><TraceChart samples={samples} xLabel="Elapsed time (s)"/></section>;
  }
  const validation = traces?.validation as Record<string, number[]> | undefined;
  if (validation && Array.isArray(validation.time_s) && Array.isArray(validation.position_rad) && Array.isArray(validation.predicted_rad)) {
    const samples = validation.time_s.map((time, index) => ({
      step: time - validation.time_s[0], measured_rad: validation.position_rad[index], fitted_rad: validation.predicted_rad[index],
    }));
    return <section><h4>Held-out joint response</h4><TraceChart samples={samples} xLabel="Elapsed time (s)"/>
      {Array.isArray(validation.residual_rad) && <><h4>Held-out residual</h4>
        <TraceChart samples={validation.time_s.map((time, index) => ({ step: time - validation.time_s[0], residual_rad: validation.residual_rad[index] }))} xLabel="Elapsed time (s)"/></>}
    </section>;
  }
  if (!traces || !Array.isArray(traces.node_position_m)) return null;
  const quantity = result.kind === 'structural_beam' ? 'displacement_m' : 'temperature_k';
  const values = traces[quantity];
  if (!Array.isArray(values) || values.length !== traces.node_position_m.length || !values.length) return null;
  const isBeam = quantity === 'displacement_m';
  const samples = traces.node_position_m.map((step, index) => ({
    step, [isBeam ? 'deflection (mm)' : 'temperature (K)']: isBeam ? values[index] * 1000 : values[index],
  }));
  return <section><h4>{quantity === 'displacement_m' ? 'Beam deflection' : 'Temperature along rod'}</h4>
    <TraceChart samples={samples} xLabel="Position along span (m)"/></section>;
}

function runTitle(run: RunSummary) { return `${run.label} · rev ${run.project_revision} · ${formatTime(run.created_at)} · ${run.id.slice(-6)}`; }

function Qualification({ result }: { result: Inputs }) {
  const dynamics = result.dynamics as Inputs | undefined;
  const checks = dynamics?.reference_qualification;
  if (!Array.isArray(checks) || !checks.length) return null;
  return <section><h4>Model qualification</h4><div className="analysis-table-scroll"><table className="data-table">
    <thead><tr><th>Reference test</th><th>Assessed joint error</th><th>Tolerance</th><th>Result</th></tr></thead>
    <tbody>{checks.map(check => <tr key={check.task}><td>{label(check.task)}</td>
      <td>{scalar(check.assessed_joint_error ?? check.max_joint_error)}</td><td>{scalar(check.joint_error_tolerance)}</td>
      <td>{check.passed ? 'Passed' : 'Failed'}</td></tr>)}</tbody>
  </table></div></section>;
}

export default function AnalysisResults({ base, adapters, runs, selected, select, reuse, refresh, refreshIndex, running, promote, jobAction, loadSuite, currentRevision }: {
  base: string; adapters: Adapter[]; runs: RunSummary[]; selected: string; select: (id: string) => void;
  reuse: (run: RunDetail) => void; refresh: () => void; running: boolean; promote?: (id: string) => Promise<void>;
  jobAction: (id: string, action: 'cancel' | 'resume') => Promise<void>;
  refreshIndex: number;
  loadSuite: (id: string) => Promise<void>; currentRevision: number;
}) {
  const active = runs.find(run => run.id === selected) ?? runs[0];
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [detailError, setDetailError] = useState('');
  const [baseline, setBaseline] = useState('');
  const [comparison, setComparison] = useState<Inputs | null>(null);
  const [compareError, setCompareError] = useState('');
  const path = active ? `${base}/${encodeURIComponent(active.id)}` : '';
  const baselineRun = runs.find(run => run.id === baseline && run.id !== active?.id);
  const baselineId = baselineRun?.id;
  const comparePath = baselineId && active ? `${base}/${encodeURIComponent(baselineId)}/compare/${encodeURIComponent(active.id)}` : '';
  useEffect(() => {
    let current = true;
    setDetailError('');
    if (path) void request<RunDetail>(path)
      .then(data => { if (current) setDetail(data); })
      .catch((error: Error) => { if (current) setDetailError(error.message); });
    return () => { current = false; };
  }, [path, active?.status, refreshIndex]);
  useEffect(() => {
    let current = true;
    setComparison(null); setCompareError('');
    if (comparePath) void request<Inputs>(comparePath)
      .then(data => { if (current) setComparison(data); })
      .catch((error: Error) => { if (current) setCompareError(error.message); });
    return () => { current = false; };
  }, [comparePath, active?.status, baselineRun?.status]);
  return <section className="project-panel" id="analysis-history">
    <header className="project-panel-header"><div><h3>Run history</h3></div>
      <button type="button" className="button secondary" onClick={refresh} disabled={running}>Refresh history</button>
    </header>
    <div className="project-form-stack">
      {active ? <>
        <label className="project-field"><span>Inspect run</span>
          <select value={active.id} onChange={event => { select(event.target.value); setBaseline(''); }}>
            {runs.map(run => <option key={run.id} value={run.id}>{runTitle(run)}</option>)}
          </select>
        </label>
        {detailError ? <Notice tone="error">{detailError}</Notice> : !detail || detail.id !== active.id ? <Loading/> : <>
          <div className="analysis-actions"><Status value={detail.status}/><span>{adapters.find(item => item.id === detail.adapter)?.label ?? label(detail.adapter)}</span>
            {['queued', 'running'].includes(detail.status) && <button type="button" className="button secondary" disabled={running} onClick={() => void jobAction(detail.id, 'cancel')}>Cancel run</button>}
            {detail.status === 'interrupted' && <button type="button" className="button secondary" disabled={running} onClick={() => void jobAction(detail.id, 'resume')}>Resume run</button>}
          </div>
          {detail.error && <Notice tone="error">{detail.error}</Notice>}
          {detail.recheck_of && detail.calibration_run_id && <div className="analysis-actions">
            <a className="text-link" href={`/api${base}/${encodeURIComponent(detail.calibration_run_id)}`} download>Calibration record</a>
            {runs.some(run => run.id === detail.recheck_of) ?
              <button type="button" className="project-inline-button" onClick={() => setBaseline(detail.recheck_of!)}>Compare with pre-calibration run</button> :
              <a className="text-link" href={`/api${base}/${encodeURIComponent(detail.recheck_of)}`} download>Pre-calibration record</a>}
          </div>}
          {detail.assessment_error && <Notice tone="warning"><strong>Inconclusive result.</strong> {detail.assessment_error}</Notice>}
          {detail.result && <><Qualification result={detail.result}/><FieldPlot result={detail.result}/><Values values={detail.result} inconclusive={Boolean(detail.assessment_error)}/></>}
          <details className="analysis-disclosure"><summary>Recorded inputs</summary><pre>{JSON.stringify(detail.inputs, null, 2)}</pre></details>
          {detail.binding_evidence && Object.keys(detail.binding_evidence).length > 0 &&
            <details className="analysis-disclosure"><summary>Project parameter sources</summary><Values values={detail.binding_evidence}/></details>}
          {detail.snapshot && <details className="analysis-disclosure"><summary>Project snapshot · revision {detail.project_revision}</summary>
            <pre>{JSON.stringify(detail.snapshot, null, 2)}</pre></details>}
          {detail.runtime && <details className="analysis-disclosure"><summary>Solver provenance</summary>
            <Values values={{ evidence_hash: detail.evidence_hash, ...detail.runtime }}/></details>}
          <div className="analysis-actions">
            <a className="button secondary" href={`/api${path}`} download={`${active.id}.json`}>Export run JSON</a>
            {detail.status === 'completed' && <a className="button secondary" href={`/api${path}/bundle`} download={`${active.id}.zip`}>Download evidence bundle</a>}
            {adapters.some(item => item.id === detail.adapter) && <button type="button" className="button secondary" disabled={running} onClick={() => reuse(detail)}>Load these inputs</button>}
            {['joint_response', 'calibration'].includes(detail.adapter) && !detail.assessment_error && detail.result?.passed === true &&
              <button type="button" className="button secondary" disabled={running || !promote || currentRevision !== detail.project_revision} onClick={() => void promote?.(detail.id)}>Apply validated calibration</button>}
          </div>
          {detail.suite_id && <details className="analysis-disclosure"><summary>Recorded suite</summary>
            <div className="analysis-actions">
              <a className="button secondary" href={`/api${base}-suite/${encodeURIComponent(detail.suite_id)}`} download={`${detail.suite_id}.json`}>Export suite JSON</a>
              <button type="button" className="button secondary" disabled={running} onClick={() => void loadSuite(detail.suite_id!)}>Load suite for this revision</button>
            </div>
          </details>}
        </>}
        {runs.length > 1 && <div className="analysis-comparison">
          <label className="project-field"><span>Compare this run against a baseline</span>
            <select value={baselineId ?? ''} onChange={event => setBaseline(event.target.value)}>
              <option value="">Choose baseline run</option>
              {runs.filter(run => run.id !== active.id).map(run => <option key={run.id} value={run.id}>{runTitle(run)}</option>)}
            </select>
          </label>
          {comparePath && (compareError ? <Notice tone="error">{compareError}</Notice> : comparison ? <>
            <Values values={comparison}/>
            <a className="button secondary" href={`/api${comparePath}`} download={`comparison-${baselineId}-${active.id}.json`}>Export comparison JSON</a>
          </> : <Loading/>)}
        </div>}
      </> : <p className="small muted">Completed and failed runs will appear here with their saved project revision.</p>}
    </div>
  </section>;
}
