import { useEffect, useRef, useState } from 'react';
import { formatTime, label, post, request } from './api';
import type { RunSummary } from './analysisInputs';
import { Icon, Notice, Status } from './components';
import type { Project } from './projectTypes';
import { ScenarioReferenceImport } from './ScenarioReferenceImport';
import type { Candidate } from './ScenarioReview';
import { ScenarioBatchResults } from './ScenarioBatchResults';
import './scenarioDiscovery.css';

type ScenarioBatch = {
  id: string; revision: number; task: string; baseline_run_id: string | null;
  status: string; error: string | null; model: string | null; created_at: string | number;
  run_supported?: boolean; clarifications: string[]; candidates: Candidate[];
};
type DiscoveryPage = {
  provider: { available: boolean; detail: string; model: string | null };
  batches: ScenarioBatch[];
};
const active = (status: string) => status === 'queued' || status === 'running';
const describe = (failure: unknown) => failure instanceof Error ? failure.message : 'The request failed.';

function downloadBatch(batch: ScenarioBatch) {
  const file = new Blob([JSON.stringify(batch, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'batch.json';
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ProjectScenarios({ project, dirty, onProjectSaved, reloadProject }: {
  project: Project; dirty: boolean; onProjectSaved: (project: Project) => void; reloadProject: () => Promise<void>;
}) {
  const base = `/projects/${encodeURIComponent(project.id)}`;
  const [task, setTask] = useState(project.goal.slice(0, 2000));
  const taskInput = useRef<HTMLTextAreaElement>(null);
  const [baseline, setBaseline] = useState('');
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [imported, setImported] = useState<string | null>(null);
  const [data, setData] = useState<DiscoveryPage | null>(null);
  const [selected, setSelected] = useState(() =>
    new URLSearchParams(window.location.hash.split('?')[1]).get('generation') ?? '');
  const [editingSetup, setEditingSetup] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [readError, setReadError] = useState('');
  const [runError, setRunError] = useState('');
  const [error, setError] = useState('');
  const submissionKey = useRef<{ body: string; key: string } | null>(null);
  const reload = () => setRefresh(value => value + 1);

  useEffect(() => {
    let current = true;
    void request<DiscoveryPage>(base + '/scenarios').then(result => {
      if (current) { setData(result); setReadError(''); }
    }).catch(failure => { if (current) setReadError(describe(failure)); });
    return () => { current = false; };
  }, [base, project.revision, refresh]);
  useEffect(() => {
    let current = true;
    void request<{ runs: RunSummary[] }>(base + '/analysis').then(result => {
      if (current) { setRuns(result.runs); setRunError(''); }
    }).catch(failure => { if (current) setRunError(describe(failure)); });
    return () => { current = false; };
  }, [base, project.revision, refresh]);
  const currentRuns = runs.filter(run => run.project_revision === project.revision);
  const selectedRun = currentRuns.find(run => run.id === baseline);
  const importedRun = currentRuns.find(run => run.id === imported);
  const importing = Boolean(imported && (!importedRun || active(importedRun.status)));
  const generating = data?.batches.some(batch => active(batch.status)) ?? false;
  useEffect(() => {
    if (!generating && !importing) return;
    const timer = window.setInterval(() => { if (!document.hidden) setRefresh(value => value + 1); }, 3500);
    return () => window.clearInterval(timer);
  }, [generating, importing]);
  const batch = data?.batches.find(item => item.id === selected) ?? data?.batches[0];
  const batchReference = runs.find(run => run.id === batch?.baseline_run_id);
  const stale = Boolean(batch && batch.revision !== project.revision);
  const canGenerate = Boolean(task.trim() && data?.provider.available && !dirty && !busy && !generating
    && !importing && (!baseline || selectedRun?.status === 'completed'));

  async function generate(runSupported: boolean) {
    if (!canGenerate || (runSupported && !baseline)) return;
    setError(''); setBusy(true);
    const body = { expected_revision: project.revision, task: task.trim(), baseline_run_id: baseline || null,
      run_supported: runSupported };
    const serialized = JSON.stringify(body);
    if (submissionKey.current?.body !== serialized) submissionKey.current = { body: serialized, key: crypto.randomUUID() };
    try {
      const result = await post<ScenarioBatch>(base + '/scenarios/generate', body, submissionKey.current.key);
      setData(previous => previous && ({ ...previous, batches: [result, ...previous.batches.filter(item => item.id !== result.id)] }));
      setSelected(result.id);
      setEditingSetup(false);
      submissionKey.current = null;
      reload();
    } catch (failure) { setError(describe(failure)); } finally { setBusy(false); }
  }
  function clarify(question: string) {
    if (!batch) return;
    setEditingSetup(true);
    if (!stale) setBaseline(batch.baseline_run_id ?? '');
    const prefix = batch.task.slice(0, 2000 - question.length - 12);
    setTask(`${prefix}\n\n${question}\n`.trimStart());
    requestAnimationFrame(() => { taskInput.current?.focus(); taskInput.current?.setSelectionRange(2000, 2000); });
  }
  function newBatch() {
    if (batch && !stale) {
      setBaseline(batch.baseline_run_id ?? '');
      setTask(batch.task);
    }
    setEditingSetup(true);
    requestAnimationFrame(() => taskInput.current?.focus());
  }
  return <div className="scenario-workspace">
    {(!batch || editingSetup) && <section className="project-panel">
      <header className="project-panel-header"><div><h3>Discover scenarios</h3>
        <p>Describe how your prototype is used and choose a reference to test the local AI’s scenarios.</p></div></header>
      <div className="project-form-stack">
        {dirty && <Notice tone="warning">Save your project changes before generating or running a scenario.</Notice>}
        <label className="project-field"><span>What operating situation should we investigate?</span>
          <textarea ref={taskInput} maxLength={2000} rows={3} value={task} onChange={event => setTask(event.target.value)}
            placeholder="What should happen, and what else is acting on the prototype at that moment?"/></label>
        <div className="scenario-reference"><label className="project-field"><span>Reference run</span>
          <select value={baseline} onChange={event => { setBaseline(event.target.value); setImported(null); }}>
            <option value="">Plan from the project brief</option>
            {baseline && !selectedRun && <option value={baseline} disabled>{importing ? 'Preparing imported reference…' : 'Reference unavailable for this revision'}</option>}
            {currentRuns.filter(run => run.status === 'completed' || run.id === baseline).map(run =>
              <option key={run.id} value={run.id}>{run.label} · {label(run.adapter)} · {formatTime(run.created_at)}{run.status === 'completed' ? '' : ' · ' + label(run.status)}</option>)}
          </select>
          <small>A completed run fixes the model, its inputs, and its pass rules for comparison.</small></label>
          <a className="text-link" href={'#' + base + '/analysis'}>Set up a reference in Analysis &amp; runs</a>
          <ScenarioReferenceImport project={project} disabled={dirty || busy} onSaved={onProjectSaved}
            onRun={id => { setBaseline(id); setImported(id); setError(''); reload(); }}/>
          {importing && <p className="small" role="status">Running the imported reference on the CPU…</p>}
          {importedRun?.status === 'completed' && <p className="small" role="status">Your reference run is complete and selected.</p>}
          {importedRun && !active(importedRun.status) && importedRun.status !== 'completed' && <Notice tone="warning">
            The reference run is {label(importedRun.status)}. {importedRun.error}</Notice>}
          {runError && <Notice tone="error">{runError} <button type="button" className="project-inline-button" onClick={reload}>Retry references</button></Notice>}
        </div>
        <div className="scenario-generator"><div>
          <strong>{data?.provider.model ?? 'Local scenario generator'}</strong>
          <span>{data?.provider.available ? 'Available on the local model server' : data?.provider.detail || 'Checking the local model server…'}</span></div>
          <button type="button" className="button secondary" onClick={() => { if (!dirty) void reloadProject(); reload(); }}
            aria-label="Refresh generator and reference availability"><Icon name="refresh" size={15}/>Refresh</button>
        </div>
        {readError && <Notice tone="error">{readError}</Notice>}
        {error && <Notice tone="error">{error}</Notice>}
        {baseline && <p className="scenario-run-scope">This batch targets at least five distinct test cases. Supported cases run on the CPU with the selected reference. Ideas that need more inputs or physics stay in the results for review.</p>}
        <div className="scenario-actions"><button type="button" className="button primary" disabled={!canGenerate}
          onClick={() => void generate(Boolean(baseline))}><Icon name="search" size={16}/>{busy || generating ? 'Generating scenarios…' :
            baseline ? 'Generate and run test cases' : 'Generate ideas from brief'}</button>
          {baseline && <button type="button" className="button secondary" disabled={!canGenerate}
            onClick={() => void generate(false)}>Generate for review</button>}
          {batch && <button type="button" className="project-inline-button" onClick={() => setEditingSetup(false)}>Back to results</button>}
        </div>
      </div></section>}
    {batch && <section className="project-panel" aria-label="Scenario review">
      <header className="project-panel-header"><div><h3>Scenario batch</h3>
        <p>{batch.task}</p></div>{!editingSetup && <button type="button" className="button secondary"
          onClick={newBatch}><Icon name="plus" size={15}/>New scenario batch</button>}</header>
      <div className="project-form-stack">
        {(data?.batches.length ?? 0) > 1 && <label className="project-field"><span>Saved generations</span>
          <select value={batch.id} onChange={event => setSelected(event.target.value)}>{data?.batches.map(item =>
            <option key={item.id} value={item.id}>{formatTime(item.created_at)} · Rev {item.revision} · {item.task.slice(0, 50)}</option>)}</select></label>}
        <p className="scenario-source">Revision {batch.revision} · {batchReference?.label ?? (batch.baseline_run_id ? 'Reference ' + batch.baseline_run_id : 'Project brief')}{batch.model && ' · ' + batch.model}</p>
        {stale && <Notice tone="warning">The project is now at revision {project.revision}. Generate a new set to test the current inputs.</Notice>}
        {active(batch.status) && <div className="scenario-generation-status" role="status"><Status value={batch.status}/>
          <p>Your local model is designing use cases. {batch.run_supported && 'Supported cases will run automatically. '}You can return to this saved batch while it works.</p></div>}
        {batch.error && <Notice tone="error">{batch.error}</Notice>}
        <ScenarioBatchResults key={batch.id} projectId={project.id} batchId={batch.id} generationStatus={batch.status}
          candidates={batch.candidates} revision={project.revision} dirty={dirty} stale={stale} refresh={refresh}
          onChange={reload} clarify={clarify}/>
        {!active(batch.status) && <div className="scenario-actions" role="group" aria-label="Download this scenario batch">
          <button type="button" className="button secondary" onClick={() => downloadBatch(batch)}>
            <Icon name="download" size={15}/>Download proposals (JSON)</button>
          <a className="button secondary" href={'/api' + base + '/scenarios/batches/' + encodeURIComponent(batch.id) + '/results'}
            download="results.json"><Icon name="download" size={15}/>Download results (JSON)</a>
        </div>}
        {batch.clarifications.length > 0 && <div><h4>Information to clarify</h4><ul className="scenario-questions">
          {batch.clarifications.map((item, i) => <li key={i}>{item} <button type="button" className="project-inline-button" onClick={() => clarify(item)}>Answer in task description</button></li>)}</ul></div>}
      </div></section>}
  </div>;
}
