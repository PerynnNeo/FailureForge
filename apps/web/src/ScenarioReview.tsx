import { useEffect, useRef, useState } from 'react';
import { label, post } from './api';
import { Notice } from './components';
import { fieldText } from './analysisInputs';
import type { RunInput } from './analysisInputs';
import { ScenarioEvidence } from './ScenarioEvidence';
import type { ScenarioExecution } from './ScenarioEvidence';

export type Candidate = {
  id: string; family_key?: string | null; dismissed: boolean; execution: ScenarioExecution | null; review?: Preview | null;
  draft: { title: string; hypothesis: string; fact_refs: string[]; operation_id: string | null;
    assumptions: string[]; missing_capability: string | null; question: string | null; shift_ms: number | null };
};
type Preview = {
  state: string; reason: string; review_note?: string | null; approval_mode?: string;
  facts: { id: string; label: string; value: string | number; unit: string; source: string }[];
  reference: RunInput | null; variant: RunInput | null; observables: string[];
  diff: Record<string, { reference: unknown; variant: unknown }>; fingerprint: string | null;
};

const states: Record<string, string> = {
  ready: 'Ready to run', needs_information: 'Needs information', needs_capability: 'Needs model support',
  invalid: 'Invalid setup', stale: 'Outdated revision',
};
const describe = (failure: unknown) => failure instanceof Error ? failure.message : 'The request failed.';

export function ScenarioReview({ projectId, revision, candidate, stale, dirty, onChange, clarify }: {
  projectId: string; revision: number; candidate: Candidate; stale: boolean; dirty: boolean;
  onChange: () => void; clarify: (question: string) => void;
}) {
  const path = `/projects/${encodeURIComponent(projectId)}/scenarios/${encodeURIComponent(candidate.id)}`;
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState('');
  const [preview, setPreview] = useState<{ confirmed: boolean; data: Preview } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const [receipt, setReceipt] = useState<ScenarioExecution | null>(null);
  const [hidden, setHidden] = useState(false);
  const pendingKey = useRef<{ body: string; key: string } | null>(null);
  const execution = candidate.execution ?? receipt;
  const dismissed = candidate.dismissed || hidden;
  const draft = candidate.draft;
  useEffect(() => {
    let current = true;
    if (!stale && !dismissed && !execution) {
      setError('');
      void post<Preview>(path + '/preview', { expected_revision: revision, confirmed })
        .then(data => { if (current) setPreview({ confirmed, data }); })
        .catch(failure => { if (current) { setError(describe(failure)); setPreview(null); } });
    }
    return () => { current = false; };
  }, [path, revision, confirmed, stale, dismissed, Boolean(execution), retry]);
  const report = candidate.review ?? (preview?.confirmed === confirmed ? preview.data : null);
  async function execute() {
    if (!report?.fingerprint || report.state !== 'ready' || !confirmed || stale || dirty) return;
    setBusy(true); setError('');
    const body = { expected_revision: revision, confirmed, fingerprint: report.fingerprint, review_note: note.trim() || undefined };
    const serialized = JSON.stringify(body);
    if (pendingKey.current?.body !== serialized) pendingKey.current = { body: serialized, key: crypto.randomUUID() };
    try {
      setReceipt(await post<ScenarioExecution>(path + '/execute', body, pendingKey.current.key));
      onChange();
    } catch (failure) { setError(describe(failure)); } finally { setBusy(false); }
  }
  async function dismiss() {
    setBusy(true); setError('');
    try { await post(path + '/dismiss', { expected_revision: revision }); setHidden(true); onChange(); }
    catch (failure) { setError(describe(failure)); } finally { setBusy(false); }
  }
  if (dismissed) return <div className="scenario-dismissed"><span>Dismissed</span> {draft.title}</div>;
  const reviewable = Boolean(report?.reference && report.variant);
  const batchExecution = candidate.review?.approval_mode === 'batch';
  const review = <>
      {draft.missing_capability && <p><strong>Model-suggested gap</strong><br/>{draft.missing_capability}</p>}
      {draft.assumptions.length > 0 && <div><h5>{batchExecution ? 'Exploratory assumptions' : execution ? 'Reviewed assumptions' : 'Assumptions to review'}</h5>
        <ul className="scenario-list">{draft.assumptions.map((item, i) => <li key={i}>{item}</li>)}</ul></div>}
      {draft.question && <div><h5>Question for your team</h5><p>{draft.question}</p>
        {!execution && !stale && <button type="button" className="project-inline-button" onClick={() => clarify(draft.question!)}>Refine the task description</button>}</div>}
      {report && <>{!execution && report.reason && report.reason !== draft.missing_capability && report.reason !== draft.question && <p>{report.reason}</p>}
        {report.facts.length > 0 && <details className="scenario-detail"><summary>Supporting project facts ({report.facts.length})</summary>
          <dl>{report.facts.map(fact => <div key={fact.id}><dt>{fact.label}</dt><dd>{fact.value} {fact.unit}<small>{fact.source}</small></dd></div>)}</dl>
        </details>}
        {reviewable && <div className="scenario-preview"><h5>Inputs that change</h5>
          <div className="analysis-table-scroll"><table className="data-table">
            <thead><tr><th scope="col">Input</th><th scope="col">Reference</th><th scope="col">What-if</th></tr></thead>
            <tbody>{Object.entries(report.diff).map(([key, values]) => <tr key={key}><th scope="row">{label(key)}</th>
              <td>{fieldText(values.reference) || 'Unset'}</td><td>{fieldText(values.variant) || 'Unset'}</td></tr>)}</tbody>
          </table></div>
          {report.observables.length > 0 && <div><h5>Pass rules</h5><ul className="scenario-list">
            {report.observables.map(rule => <li key={rule}>{rule}</li>)}</ul></div>}
          <details className="scenario-detail"><summary>Complete solver inputs</summary>
            <h5>Reference</h5><pre>{JSON.stringify(report.reference, null, 2)}</pre>
            <h5>What-if</h5><pre>{JSON.stringify(report.variant, null, 2)}</pre></details>
        </div>}
      </>}
    </>;
  return <article className="scenario-card">
    <div className="scenario-row"><h4>{draft.title}</h4>
      <span className={'scenario-state ' + (execution || report?.state === 'ready' ? 'is-ready' : '')}>
        {execution ? 'Submitted' : stale ? 'Outdated revision' : reviewable && !confirmed ? 'Review required' :
          report ? states[report.state] || label(report.state) : 'Checking setup'}
      </span></div>
    <p>{draft.hypothesis}</p>
    {execution ? <><ScenarioEvidence projectId={projectId} execution={execution}/>
      {candidate.review?.review_note && <div><h5>Engineer’s review note</h5><p className="scenario-saved-note">{candidate.review.review_note}</p></div>}
      <details className="scenario-detail"><summary>{batchExecution ? 'Test setup and supporting facts' : 'Approved test and supporting facts'}</summary>
        <div className="scenario-record">{review}</div></details></> : <>{review}
      {!stale && (reviewable || confirmed) && <label className="project-field">
        <span>Review note (optional)</span><textarea rows={2} maxLength={600} disabled={busy || dirty}
          value={note} onChange={event => setNote(event.target.value)}
          placeholder="Record the interpretation or assumptions you approve for these exact inputs."/>
      </label>}
      {!stale && (reviewable || confirmed) && <label className="scenario-approval">
        <input type="checkbox" checked={confirmed} disabled={dirty || busy}
          onChange={event => { setError(''); setConfirmed(event.target.checked); }}/>
        <span>I confirm this reference and proposed change apply to my design.</span>
      </label>}
      {error && <Notice tone="error">{error} <button type="button" className="project-inline-button" onClick={() => setRetry(n => n + 1)}>Recheck preview</button></Notice>}
      {!stale && <div className="scenario-actions">
        {(reviewable || confirmed) && <button type="button" className="button primary" disabled={busy || dirty || !confirmed || report?.state !== 'ready'}
          onClick={() => void execute()}>{busy ? 'Saving…' : 'Run reference and what-if'}</button>}
        <button type="button" className="project-inline-button" disabled={busy || dirty} onClick={() => void dismiss()}>Dismiss suggestion</button>
      </div>}
    </>}
  </article>;
}
