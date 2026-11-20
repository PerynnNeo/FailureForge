import { useEffect, useState } from 'react';
import { label, request } from './api';
import type { RunDetail } from './analysisInputs';
import { projectBatchHref } from './campaignHistory';
import { comparisonMeasurements } from './comparisonMeasurements';
import { Notice } from './components';
import { measuredNumber } from './recordedFields';
import { StationComparison } from './StationComparison';

export type ScenarioExecution = { suite_id: string; runs: [string, string] };

function outcome(run: RunDetail) {
  if (run.error || run.assessment_error) return 'Inconclusive';
  if (run.status !== 'completed') return label(run.status);
  return run.result?.passed === true ? 'Passed' : run.result?.passed === false ? 'Failed' : 'Measurement only';
}

function resultText(value?: boolean) {
  return value === true ? 'Passed' : value === false ? 'Failed' : '';
}

export function ScenarioEvidence({ projectId, execution }: { projectId: string; execution: ScenarioExecution }) {
  const [pair, setPair] = useState<RunDetail[] | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [referenceId, variantId] = execution.runs;
  useEffect(() => {
    let current = true;
    let timer: number;
    async function read() {
      try {
        const results = await Promise.all([referenceId, variantId].map(id =>
          request<RunDetail>(`/projects/${encodeURIComponent(projectId)}/analysis/${encodeURIComponent(id)}`)));
        if (!current) return;
        setPair(results); setError('');
        if (results.some(run => ['queued', 'running'].includes(run.status))) timer = window.setTimeout(read, 1800);
      } catch (failure) { if (current) setError(failure instanceof Error ? failure.message : 'Results could not be loaded.'); }
    }
    void read();
    return () => { current = false; window.clearTimeout(timer); };
  }, [referenceId, variantId, projectId, retry]);

  const records = pair?.map(comparisonMeasurements) ?? [];
  const metrics = [...new Set(records.flatMap(record => record.measurements.map(row => row.name)))];
  const outcomes = [...new Set(records.flatMap(record => record.outcomes.map(row => row.name)))];
  return <section className="scenario-evidence" aria-label="Simulation results">
    <div className="scenario-row"><h5>Simulation results</h5>
      <a className="text-link" href={projectBatchHref(projectId, execution.suite_id, variantId)}>Open run evidence</a></div>
    {error && <Notice tone="error">{error} <button className="project-inline-button" onClick={() => setRetry(n => n + 1)}>Retry</button></Notice>}
    {!pair && !error && <p role="status">Reading the two recorded runs…</p>}
    {pair && <div className="analysis-table-scroll"><table className="data-table scenario-table">
      <thead><tr><th scope="col">Measurement</th><th scope="col">Reference</th><th scope="col">What-if</th></tr></thead>
      <tbody><tr><th scope="row">Overall result</th>{pair.map(run => <td key={run.id}><strong>{outcome(run)}</strong>
        {(run.error || run.assessment_error) && <small>{run.error || run.assessment_error}</small>}</td>)}</tr>
        {metrics.map(name => <tr key={name}><th scope="row">{name}</th>{records.map((record, i) => {
          const row = record.measurements.find(item => item.name === name);
          return <td key={i}>{row ? <>{measuredNumber(row.value)} {row.unit}
            {row.maximum !== undefined && <small>Limit ≤ {measuredNumber(row.maximum)} {row.unit}</small>}
            {!pair[i].assessment_error && !pair[i].error && row.passed !== undefined && <small>{resultText(row.passed)}</small>}</> : '—'}</td>;
        })}</tr>)}
        {outcomes.map(name => <tr key={name}><th scope="row">{name}</th>{records.map((record, i) =>
          <td key={i}>{pair[i].assessment_error || pair[i].error ? 'Inconclusive' : resultText(record.outcomes.find(row => row.name === name)?.passed) || '—'}</td>)}</tr>)}
      </tbody></table></div>}
    <StationComparison reference={pair?.[0]} comparison={pair?.[1]}/>
  </section>;
}
