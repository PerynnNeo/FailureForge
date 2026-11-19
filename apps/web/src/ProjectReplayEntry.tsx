import { useEffect, useState } from 'react';
import { request } from './api';
import type { Condition } from './campaignCompare';
import { CompareWithReference } from './CompareWithReference';
import { Loading, Notice } from './components';
import ReplayWorkspace from './ReplayWorkspace';

type EvidencePair = {
  project_revision: number; field: string; label: string; suite_id: string | null;
  left: Condition; right: Condition;
};

export function ProjectReplayEntry({ projectId }: {projectId: string}) {
  const base = '/projects/' + encodeURIComponent(projectId) + '/analysis';
  const [response, setResponse] = useState<{pair: EvidencePair | null} | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    setError('');
    setResponse(null);
    void request<{pair: EvidencePair | null}>('/projects/' + encodeURIComponent(projectId) + '/replay-pair').then(
      data => { if (current) setResponse(data); },
      failure => { if (current) setError((failure as Error).message); },
    );
    return () => { current = false; };
  }, [projectId, attempt]);
  if (!response && !error) return <Loading/>;
  const pair = response?.pair;
  if (!pair) return <>
    {error && <Notice tone="warning">The pass/fail comparison could not load. {error}{' '}
      <button type="button" className="project-inline-button" onClick={() => setAttempt(n => n + 1)}>Retry</button>
    </Notice>}
    <ReplayWorkspace projectId={projectId} runId={null} batchId={null}/>
  </>;
  return <section className="project-panel" aria-label="Matched pass and failure">
    <header className="project-panel-header"><div><h3>Passing and failing conditions</h3>
      <p>{pair.label} changed between these runs. Both used revision {pair.project_revision}, the same solver and the same acceptance settings.</p>
    </div></header>
    <div className="project-form-stack">
      <CompareWithReference base={base} runs={[pair.left, pair.right]} field={pair.field}
        reference={pair.left} selectedId={pair.right.id} fixedPair/>
      <div className="analysis-actions">
        <a className="button secondary" href={'#'+base+'?'+new URLSearchParams({run:pair.right.id})}>Inspect failed run</a>
        {pair.suite_id && <a className="button secondary" href={'#'+base+'?'+new URLSearchParams({batch:pair.suite_id})}>View campaign conditions</a>}
        <a className="text-link" href={'#'+base+'?replay=latest'}>Browse individual replays</a>
      </div>
    </div>
  </section>;
}
