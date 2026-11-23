import { useEffect, useState } from 'react';
import { emptyProject } from './projectTypes';
import type { Project } from './projectTypes';
import type { RunDetail } from './analysisInputs';
import { post, request } from './api';
import { Icon, Loading, Notice, SectionHeading } from './components';
import { savedShelfInputs, shelfInputs, shelfReading, shelfSuiteLabel, shelfTests } from './shelfExample';
import type { ShelfInputs } from './shelfExample';
import './shelfWalkthrough.css';

const fmt = (n: number) => String(Number(n.toPrecision(4)));
const errorText = (error: unknown) => error instanceof Error ? error.message : 'The request could not be completed.';
const placements = ['Spread across the shelf', 'Placed at the free edge'];

function ShelfDiagram({ edge }: { edge: boolean }) {
  return <div className={'shelf-diagram' + (edge ? ' edge' : '')} aria-hidden="true">
    <div className="shelf-clamp"/><div className="shelf-deck"/>
    <div className="shelf-load">{(edge ? [0] : [0,1,2,3,4]).map(i => <i key={i}/>)}</div>
  </div>;
}

export function ShelfStart() {
  const [inputs, setInputs] = useState<ShelfInputs | null>(null);
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    async function load() {
      const response = await fetch('/examples/beam-reference.json', {signal: controller.signal});
      if (!response.ok) throw new Error('The example model could not be loaded.');
      const model = await response.json();
      if (model.adapter !== 'structural_beam' || !shelfInputs(model.inputs)) throw new Error('The example model has incomplete inputs.');
      if (!controller.signal.aborted) setInputs(model.inputs);
    }
    void load().catch(e => { if (!controller.signal.aborted) setError(errorText(e)); });
    return () => controller.abort();
  }, [retry]);

  async function start() {
    if (!inputs || busy) return;
    setBusy(true); setError('');
    // A reload or lost response can safely replay either of the two writes.
    const url = new URL(window.location.href);
    const [path, query] = url.hash.split('?');
    const params = new URLSearchParams(query);
    const attempt = params.get('attempt') || crypto.randomUUID();
    params.set('attempt', attempt);
    url.hash = path + '?' + params;
    window.history.replaceState(null, '', url);
    try {
      const project = await post<Project>('/projects', { ...emptyProject(), name: 'Shelf bending example',
        entry_stage: 'simulation', analysis_type: 'structural',
        goal: 'Find how moving the same load to the free edge changes shelf bending.',
        success_criteria: 'Maximum deflection must stay within ' + fmt(inputs.max_displacement_m * 1000) + ' mm.',
        notes: 'Guided example using the supplied rectangular beam model with a rigid clamp and a static load.' },
        'shelf-project-v1-' + attempt);
      const suite = await post<{suite_id: string}>('/projects/' + project.id + '/analysis-suite',
        {expected_revision: project.revision, label: shelfSuiteLabel, tests: shelfTests(inputs)}, 'shelf-suite-v1-' + attempt);
      if (window.location.hash === url.hash) window.location.hash = '/projects/' + project.id + '?tab=shelf&batch=' + encodeURIComponent(suite.suite_id);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <>
    <a className="back-link" href="#/projects">All projects</a>
    <SectionHeading eyebrow="GUIDED EXAMPLE" title="How far will this shelf bend?" description="Run a small experiment on your laptop. The shelf model, load and bending limit are supplied."/>
    {!inputs && !error && <Loading/>}
    {error && <Notice tone="error">{error} {!inputs && <button className="project-inline-button" onClick={() => setRetry(v => v + 1)}>Retry loading the model</button>}</Notice>}
    {inputs && <section className="shelf-walk">
      <h3>Move the same load</h3>
      <p>A {fmt(inputs.length_m * 1000)} mm shelf is clamped at one end. Compare a {fmt(inputs.length_m * inputs.distributed_load_n_per_m)} N load in two positions.</p>
      <div className="shelf-cases">{placements.map((place, i) => <div className="shelf-case" key={place}>
        <ShelfDiagram edge={i === 1}/><strong>{place}</strong></div>)}</div>
      <p>The solver will measure the largest bend in each case and check it against a <b>{fmt(inputs.max_displacement_m * 1000)} mm</b> limit.</p>
      <div className="shelf-actions"><button className="button primary" disabled={busy} onClick={() => void start()}><Icon name="play" size={16}/>{busy ? 'Preparing the two runs…' : 'Run shelf example'}</button>
        <a className="text-link" href="#/projects/new">Start my own project</a></div>
      <small>Running saves an example project in this workspace. Both simulations use the CPU.</small>
    </section>}
  </>;
}

export function ShelfResults({ project, batch }: { project: Project; batch: string }) {
  const [runs, setRuns] = useState<RunDetail[] | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const path = '/projects/' + encodeURIComponent(project.id);
  const evidence = '#' + path + '/analysis?batch=' + encodeURIComponent(batch);
  useEffect(() => {
    let current = true;
    let timer: number;
    async function poll() {
      try {
        const receipt = await request<{runs: RunDetail[]}>(path + '/analysis-suite/' + encodeURIComponent(batch));
        if (!current) return;
        setError(''); setRuns(receipt.runs);
        if (receipt.runs.some(run => ['queued', 'running'].includes(run.status))) timer = window.setTimeout(poll, 1250);
      } catch (e) { if (current) setError(errorText(e)); }
    }
    void poll();
    return () => { current = false; window.clearTimeout(timer); };
  }, [path, batch, retry]);
  const inputs = runs && savedShelfInputs(runs);
  const readings = runs?.map(shelfReading) ?? [];
  const waiting = runs?.some(run => ['queued','running'].includes(run.status));
  const [spread, edge] = readings;
  return <>
    <a className="back-link" href={'#' + path}>Back to project</a>
    <SectionHeading eyebrow="GUIDED EXAMPLE" title="Shelf bending results" description="See how moving the load affects the maximum bend."/>
    {error && <Notice tone="error">{error} <button className="project-inline-button" onClick={() => setRetry(v => v+1)}>Retry loading results</button></Notice>}
    {!runs && !error && <Loading/>}
    {runs && !inputs && <Notice>This batch has a different setup. <a href={evidence}>Open its recorded runs</a>.</Notice>}
    {runs && inputs && <section className="shelf-walk">
      <h3>{waiting ? 'Running the comparison' : 'What happened to the shelf?'}</h3>
      <p>Both cases use the same {fmt(inputs.length_m * inputs.distributed_load_n_per_m)} N load and a {fmt(inputs.max_displacement_m * 1000)} mm bending limit.</p>
      <div className="shelf-cases" aria-live="polite">{runs.map((run, i) => {
        const reading = readings[i];
        return <article className="shelf-case" key={run.id}><ShelfDiagram edge={i === 1}/><h4>{placements[i]}</h4>
          {reading ? <><span className={'shelf-verdict ' + (reading.passed ? 'pass' : 'fail')}>{reading.passed ? 'Passed' : 'Failed'}</span>
            <p><strong>{fmt(reading.mm)} mm</strong> maximum bend</p></> : <p>{run.status === 'queued' ? 'Waiting for the solver…' : run.status === 'running' ? 'Simulating…' : 'No verified verdict. ' + (run.assessment_error || run.error || run.status)}</p>}
        </article>;
      })}</div>
      {spread && edge && <p role="status">{edge.mm > spread.mm ? 'The shelf bent more with the load at the free edge.' : edge.mm < spread.mm ? 'The shelf bent less with the load at the free edge.' : 'Both placements produced the same maximum bend.'} {spread.passed !== edge.passed && (edge.passed ? 'Only the edge load stayed within the limit.' : 'Only the spread load stayed within the limit.')}</p>}
      {!waiting && <div className="shelf-actions">
        {spread && edge ? <a className="button primary" href="#/projects/new">Test my own prototype<Icon name="chevron" size={16}/></a> :
          <a className="button primary" href="#/projects/new?example=shelf">Try the example again</a>}
        <a className="text-link" href={evidence}>Inspect the recorded runs</a>
        {spread && project.revision === runs[0].project_revision && <a className="text-link" href={'#' + path + '?tab=scenarios&example=shelf&reference=' + encodeURIComponent(runs[0].id)}>Explore more shelf scenarios</a>}</div>}
    </section>}
  </>;
}
