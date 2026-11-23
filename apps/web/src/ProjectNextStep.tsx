import { useEffect, useState } from 'react';
import { request } from './api';
import type { RunSummary } from './analysisInputs';
import { Icon } from './components';
import { isWorking, projectNextAction, type ScenarioActivity } from './projectNextAction';
import type { Project } from './projectTypes';
import { findShelfSuite } from './shelfExample';
import './projectNextStep.css';

export function ProjectNextStep({ project }: { project: Project }) {
  const [history, setHistory] = useState<{ runs: RunSummary[]; discovery: ScenarioActivity } | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const path = '/projects/' + encodeURIComponent(project.id);
  useEffect(() => {
    let current = true;
    let timer: number;
    async function load() {
      try {
        const [analysis, discovery] = await Promise.all([
          request<{ runs: RunSummary[] }>(path + '/analysis'),
          request<ScenarioActivity>(path + '/scenarios'),
        ]);
        if (!current) return;
        setHistory({ runs: analysis.runs, discovery });
        setError('');
        if (analysis.runs.some(r => r.project_revision === project.revision && isWorking(r.status)) ||
            discovery.batches.some(b => b.revision === project.revision && isWorking(b.status))) {
          timer = window.setTimeout(load, 3500);
        }
      } catch (cause) {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load the project history.');
      }
    }
    void load();
    return () => { current = false; window.clearTimeout(timer); };
  }, [path, project.revision, retry]);

  const currentRuns = history?.runs.filter(run => run.project_revision === project.revision) ?? [];
  const next = history && projectNextAction(project, history.runs, history.discovery, findShelfSuite(currentRuns));
  return <section className="project-next-step" data-tour="project-journey" aria-label="Your next step">
    <div>
      <span className="eyebrow">Your next step</span>
      {error ? <><h3>Check your project history</h3><p role="alert">{error}</p></> :
        next ? <><h3>{next.title}</h3><p>{next.description}</p></> :
          <p role="status">Checking for saved tests…</p>}
    </div>
    {error ? <div className="project-next-buttons">
      <button type="button" className="button secondary" onClick={() => { setError(''); setRetry(n => n + 1); }}>Retry</button>
      <a className="text-link" href={'#' + path + '/analysis'}>Open analysis &amp; runs</a>
    </div> : next && <div className="project-next-buttons">
      <a className="button primary" href={next.action.href}>{next.action.label}<Icon name="chevron" size={16}/></a>
      {next.alternative && <a className="text-link" href={next.alternative.href}>{next.alternative.label}</a>}
    </div>}
  </section>;
}
