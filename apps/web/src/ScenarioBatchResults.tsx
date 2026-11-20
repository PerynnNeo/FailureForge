import { useEffect, useRef, useState } from 'react';
import { post, request } from './api';
import { Notice } from './components';
import { measuredNumber } from './recordedFields';
import { projectBatchHref } from './campaignHistory';
import { ScenarioReview } from './ScenarioReview';
import type { Candidate } from './ScenarioReview';
import { groupScenarioFamilies } from './scenarioFamilies';
import { coverageText, reportInProgress, verdictLabel } from './scenarioVerdicts';
import type { BatchReport, ScenarioResult } from './scenarioVerdicts';

const describe = (failure: unknown) => failure instanceof Error ? failure.message : 'The request failed.';

function Measurement({ value }: { value: ScenarioResult['measurement'] }) {
  if (!value || value.value === null) return <span aria-label="No recorded measurement">—</span>;
  const format = (quantity: number) => measuredNumber(quantity) + (value.unit ? ' ' + value.unit : '');
  return <><strong>{format(value.value)}</strong><small>{value.name}</small>
    {value.reference_value != null && <small>Reference {format(value.reference_value)}</small>}
    {value.limit != null && <small>Limit ≤ {format(value.limit)}</small>}</>;
}

export function ScenarioBatchResults({ projectId, batchId, generationStatus, candidates, revision, dirty, stale,
  refresh, onChange, clarify }: {
  projectId: string; batchId: string; generationStatus: string; candidates: Candidate[]; revision: number;
  dirty: boolean; stale: boolean; refresh: number; onChange: () => void; clarify: (question: string) => void;
}) {
  const endpoint = `/projects/${encodeURIComponent(projectId)}/scenarios/batches/${encodeURIComponent(batchId)}`;
  const [report, setReport] = useState<BatchReport | null>(null);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [retry, setRetry] = useState(0);
  const requestKey = useRef<string | null>(null);
  const detail = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Generation history already polls until the provider publishes its cases.
    if (['queued', 'running'].includes(generationStatus)) return;
    let current = true;
    let timer: number;
    async function load() {
      try {
        const result = await request<BatchReport>(endpoint + '/results');
        if (!current) return;
        setReport(result); setError('');
        if (reportInProgress(result)) timer = window.setTimeout(load, 2500);
      } catch (failure) {
        if (current) setError(describe(failure));
      }
    }
    void load();
    return () => { current = false; window.clearTimeout(timer); };
  }, [endpoint, generationStatus, refresh, revision, retry]);

  async function executeAll() {
    if (dirty || stale || submitting) return;
    setSubmitting(true); setError('');
    requestKey.current ??= crypto.randomUUID();
    try {
      const result = await post<BatchReport>(endpoint + '/execute-all', { expected_revision: revision }, requestKey.current);
      setReport(result); requestKey.current = null; onChange();
    } catch (failure) { setError(describe(failure)); } finally { setSubmitting(false); }
  }

  const open = (candidateId: string) => {
    setSelected(candidateId);
    requestAnimationFrame(() => { detail.current?.focus({ preventScroll: true }); detail.current?.scrollIntoView({ block: 'start' }); });
  };
  const rowById = new Map(report?.rows.map(row => [row.candidate_id, row]));
  const grouped = groupScenarioFamilies(candidates);
  const currentCandidate = candidates.find(item => item.id === selected);
  const currentRow = rowById.get(selected);
  const ready = report?.rows.filter(item => item.state === 'ready').length ?? 0;
  const counts = report?.counts;
  const isGenerating = ['queued', 'running'].includes(generationStatus);
  return <section className="scenario-results" aria-label="Batch results">
    {error && <Notice tone="error">{error} <button type="button" className="project-inline-button"
      onClick={() => setRetry(n => n + 1)}>Refresh results</button></Notice>}
    {!report && !error && !isGenerating && <p role="status">Reading the batch results…</p>}
    {report?.execution_error && <Notice tone="warning">{report.execution_error}</Notice>}
    {report && counts && !isGenerating && <>
      <div className="scenario-results-heading"><div><h4>Test results</h4><p>{coverageText(report)}</p></div>
        {ready > 0 && !stale && <button type="button" className="button primary" disabled={dirty || submitting}
          onClick={() => void executeAll()}>{submitting ? 'Submitting tests…' : `Run all ${ready} supported ${ready === 1 ? 'case' : 'cases'}`}</button>}
      </div>
      {report.rows.length > 0 ? <>
        <div className="scenario-scoreboard" aria-label="Case totals" aria-live="polite">
          {[[counts.passed, 'Passed', 'passed'], [counts.failed, 'Failed', 'failed'],
            [counts.pending, 'In progress', 'running'], [counts.measurement_only, 'Measurement only', 'measurement_only'],
            [counts.blocked, 'Blocked', 'blocked'], [counts.inconclusive, 'Inconclusive', 'inconclusive']].map(([count, name, state]) =>
              (count !== 0 || state === 'passed' || state === 'failed') && <span key={state} className={'scenario-total total-' + state}>
                <strong>{count}</strong> {name}</span>)}
        </div>
        <div className="analysis-table-scroll"><table className="data-table scenario-table scenario-results-table">
          <thead><tr><th scope="col">Use case</th><th scope="col">Result</th><th scope="col">Measured what-if</th>
            <th scope="col"><span className="sr-only">Case details</span></th></tr></thead>
          {grouped.map(group => <tbody key={group.candidates[0].id}>
            {group.candidates.length > 1 && <tr className="scenario-family-heading">
              <th colSpan={4} scope="rowgroup">{group.title} · {group.candidates.length} variations</th></tr>}
            {group.candidates.map(candidate => {
              const row = rowById.get(candidate.id);
              if (!row) return null;
              return <tr key={row.candidate_id} className={selected === row.candidate_id ? 'selected-result' : undefined}>
                <th scope="row">{row.title}{row.applied_change && <small>{row.applied_change}</small>}</th>
                <td><span className={'scenario-state state-' + row.state}>{verdictLabel(row.state)}</span>
                  {row.reason && ['needs_information', 'needs_capability', 'invalid', 'stale', 'inconclusive'].includes(row.state) && <small>{row.reason}</small>}</td>
                <td><Measurement value={row.measurement}/></td>
                <td><button type="button" className="project-inline-button" aria-label={'Inspect ' + row.title}
                  onClick={() => open(row.candidate_id)}>Inspect</button>
                  {row.suite_id && <a className="text-link" href={projectBatchHref(projectId, row.suite_id, row.variant_run_id)}>Run evidence</a>}</td>
              </tr>;
            })}
          </tbody>)}
        </table></div>
      </> : <p>{generationStatus === 'completed' ? 'This generation returned no simulation cases.' : 'No cases were submitted.'}</p>}
    </>}
    {currentCandidate && <div className="scenario-result-detail" ref={detail} tabIndex={-1}>
      <div className="scenario-row"><h4>Case details</h4><button type="button" className="project-inline-button" onClick={() => setSelected('')}>Close details</button></div>
      {currentRow?.applied_change && <p><strong>Simulated change</strong><br/>{currentRow.applied_change}</p>}
      <ScenarioReview key={currentCandidate.id} projectId={projectId} revision={revision} candidate={currentCandidate}
        dirty={dirty} stale={stale} onChange={onChange} clarify={clarify}/>
    </div>}
  </section>;
}
