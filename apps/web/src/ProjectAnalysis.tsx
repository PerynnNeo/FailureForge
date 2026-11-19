import { useCallback, useEffect, useRef, useState } from 'react';
import { label, post, request } from './api';
import { Loading, Notice } from './components';
import { fieldCaption, fieldText, inputFields, parseFields } from './analysisInputs';
import type { Adapter, InputField, Inputs, RunDetail, RunInput, RunSummary } from './analysisInputs';
import AnalysisResults from './AnalysisResults';
import ProjectSweeps from './ProjectSweeps';
import EnvironmentMatrix from './EnvironmentMatrix';
import type { Project } from './projectTypes';
import type { ProjectTourCapabilities } from './projectTutorial';

type Catalog = { adapters: Adapter[]; runs: RunSummary[] };
type Rechecks = { suite_id: string | null; run_ids: string[]; previous_run_ids: string[]; more_available: boolean };
const assetFields: Record<string, { kind: string; extension: string; empty?: string }> = {
  model_asset_id: { kind: 'robot_model', extension: '.urdf', empty: 'Use the two-finger reference hand' },
  controller_asset_id: { kind: 'controller', extension: '.json', empty: 'Use the default controller' },
  cad_asset_id: { kind: 'cad', extension: '.stl' },
  bom_asset_id: { kind: 'bom', extension: '.csv', empty: 'Skip bill of materials' }, training_asset_id: { kind: 'measurements', extension: '.csv' },
  validation_asset_id: { kind: 'measurements', extension: '.csv' },
};
const editorValues = (inputs: Inputs) => Object.fromEntries(Object.entries(inputs).map(([key, value]) => [key, fieldText(value)]));
const errorText = (error: unknown) => error instanceof Error ? error.message : 'The request failed.';

function InputControl({ field, draft, update, project }: {
  field: InputField; draft: Record<string, string>; update: (value: string) => void; project: Project;
}) {
  const { name, schema, type, required } = field;
  const value = draft[name] ?? '';
  const filter = assetFields[name];
  const assets = filter ? project.assets.filter(asset => asset.kind === filter.kind &&
    (!filter.extension || asset.filename.toLowerCase().endsWith(filter.extension))) : [];
  return <label className={`project-field ${type === 'array' || type === 'object' ? 'analysis-wide' : ''}`}>
    <span>{fieldCaption(field)}{required && ' *'}</span>
    {filter ? <select value={value} required={required} disabled={name === 'controller_asset_id' && draft.mode !== 'mujoco_pd'} onChange={event => update(event.target.value)}>
      <option value="">{filter.empty ?? 'Select an attached file'}</option>
      {assets.map(asset => <option value={asset.id} key={asset.id}>{asset.filename}</option>)}
    </select> : schema.const !== undefined ?
      <input value={value} readOnly/> : schema.enum || type === 'boolean' ?
      <select value={value} required={required} onChange={event => update(event.target.value)}>
        {!required && <option value="">Use default</option>}
        {(schema.enum ?? [true, false]).map(option => <option key={fieldText(option)} value={fieldText(option)}>{fieldText(option)}</option>)}
      </select> : type === 'array' || type === 'object' ?
      <textarea className="analysis-json" rows={Math.min(12, Math.max(3, value.split('\n').length))} value={value} required={required}
        spellCheck={false} onChange={event => update(event.target.value)}/> :
      <input type={type === 'number' || type === 'integer' ? 'number' : 'text'} value={value} required={required}
        min={schema.minimum} max={schema.maximum} step={type === 'integer' ? 1 : 'any'} onChange={event => update(event.target.value)}/>}
    {filter && !assets.length && <small>Attach a {filter.extension} file under Files to use it here.</small>}
    {name === 'model_asset_id' && <small>Match target joint and tip link names to the URDF. Dynamic tracking requires supported primitive geometry and physical properties.</small>}
    {name === 'controller_asset_id' && <small>MuJoCo PD mode accepts controller settings from an attached JSON file.</small>}
    {schema.description && <small>{schema.description}</small>}
  </label>;
}

export default function ProjectAnalysis({ project, dirty, reload, notify, matrixRequest, onTourCapabilities }: {
  project: Project; dirty: boolean; reload: () => Promise<void>; notify: (message: string) => void; matrixRequest: number;
  onTourCapabilities: (capabilities: ProjectTourCapabilities | null) => void;
}) {
  const base = `/projects/${encodeURIComponent(project.id)}/analysis`;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [matrixVisible, setMatrixVisible] = useState(false);
  const hasModels = Boolean(catalog?.adapters.length);
  const canRunMatrix = Boolean(catalog?.adapters.some(item => item.id === 'packaging_lift'));
  const hasMatrix = canRunMatrix || matrixVisible;
  const runCount = catalog?.runs.length;
  useEffect(() => {
    onTourCapabilities(runCount === undefined ? null : { hasModels, hasMatrix, runCount });
  }, [onTourCapabilities, hasModels, hasMatrix, runCount]);
  const [catalogError, setCatalogError] = useState('');
  const [error, setError] = useState('');
  const [adapterId, setAdapterId] = useState('');
  const [runLabel, setRunLabel] = useState('');
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [suite, setSuite] = useState<RunInput[]>([]);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [promotion, setPromotion] = useState<{ revision: number; rechecks: Rechecks } | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  const lastSubmission = useRef<{ body: string; key: string } | null>(null);
  const refresh = () => setRefreshIndex(index => index + 1);
  const choose = useCallback((adapter: Adapter, inputs?: Inputs, title = adapter.id === 'calibration' ? `${adapter.label} (example measurements)` : adapter.label, bound: Record<string, string> = {}) => {
    const next = editorValues(inputs ?? adapter.example);
    if (!inputs) for (const name of Object.keys(assetFields)) delete next[name];
    setAdapterId(adapter.id); setDraft(next); setRunLabel(title); setBindings(bound);
  }, []);
  useEffect(() => {
    let current = true;
    void request<Catalog>(base).then(data => {
      if (!current) return;
      setCatalog(data); setCatalogError('');
      if (data.adapters.length && !data.adapters.some(item => item.id === adapterId)) {
        const preferred = project.robot_template === 'packaging_lift_v1' && data.adapters.find(item => item.id === 'packaging_lift');
        choose(preferred || data.adapters[0]);
      }
    }).catch((failure: Error) => { if (current) setCatalogError(failure.message); });
    return () => { current = false; };
  }, [base, project.revision, project.robot_template, refreshIndex, adapterId, choose]);
  const activeRuns = catalog?.runs.some(run => run.status === 'queued' || run.status === 'running');
  useEffect(() => {
    if (!activeRuns) return;
    const timer = window.setInterval(() => { if (!document.hidden) setRefreshIndex(index => index + 1); }, 2500);
    return () => window.clearInterval(timer);
  }, [activeRuns]);
  const adapter = catalog?.adapters.find(item => item.id === adapterId);
  const velocityServo = adapterId === 'robot_motion' && draft.mode === 'velocity_servo';
  const usesTimeConstant = velocityServo && Boolean(bindings.time_constant_s || draft.time_constant_s?.trim());
  const fields = adapter ? inputFields(adapter).filter(field =>
    !(adapterId === 'robot_motion' && field.name === 'time_constant_s' && !velocityServo) &&
    !(usesTimeConstant && field.name === 'gain_per_s')) : [];
  function updateField(name: string, value: string) {
    setDraft(previous => {
      const next = { ...previous, [name]: value };
      if (adapter?.id === 'robot_motion' && next.mode !== 'mujoco_pd') delete next.controller_asset_id;
      return next;
    });
  }
  function currentTest(): RunInput {
    if (!adapter || !runLabel.trim()) throw new Error('Choose an analysis and enter a run label.');
    const inputs = parseFields(fields.filter(field => !bindings[field.name]), draft);
    const activeBindings = Object.fromEntries(fields.filter(field => bindings[field.name]).map(field => [field.name, bindings[field.name]]));
    return { label: runLabel.trim(), adapter: adapter.id, inputs, ...(Object.keys(activeBindings).length ? { bindings: activeBindings } : {}) };
  }
  function addTest() {
    if (!formRef.current?.reportValidity()) return;
    try { const test = currentTest(); setSuite(items => [...items, test]); setError(''); }
    catch (failure) { setError(errorText(failure)); }
  }
  async function execute(asSuite: boolean) {
    if (busy || dirty) return;
    setError(''); setBusy(true);
    try {
      const body = asSuite ? { expected_revision: project.revision, tests: suite } : { ...currentTest(), expected_revision: project.revision };
      const encoded = JSON.stringify(body);
      if (lastSubmission.current?.body !== encoded) lastSubmission.current = { body: encoded, key: crypto.randomUUID() };
      if (asSuite) {
        const data = await post<{ runs: RunSummary[] }>(`${base}-suite`, body, lastSubmission.current.key);
        setSuite([]); setSelected(data.runs[0]?.id ?? '');
        const failures = data.runs.filter(run => run.error || run.status === 'failed' || run.status === 'error');
        if (failures.length) setError(failures.map(run => `${run.label}: ${run.error ?? run.status}`).join('\n'));
        notify(`Queued ${data.runs.length} ${data.runs.length === 1 ? 'run' : 'runs'}. Follow progress in run history.`);
      } else {
        const run = await post<RunSummary>(base, body, lastSubmission.current.key);
        setSelected(run.id); notify('Analysis queued. Follow progress in run history.');
      }
      lastSubmission.current = null;
    } catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); refresh(); }
  }
  async function jobAction(id: string, action: 'cancel' | 'resume') {
    if (busy) return;
    setBusy(true); setError('');
    try {
      await post(`${base}/${encodeURIComponent(id)}/${action}`);
      notify(action === 'resume' ? 'Analysis queued to resume.' : 'Cancellation requested.');
    } catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); refresh(); }
  }
  async function loadSuite(id: string) {
    setBusy(true); setError('');
    try {
      const { runs } = await request<{ runs: RunDetail[] }>(`${base}-suite/${encodeURIComponent(id)}`);
      if (suite.length + runs.length > 16) throw new Error('A suite supports up to 16 tests. Remove existing entries to make room.');
      setSuite(items => [...items, ...runs.map(run => run.definition ?? { label: run.label, adapter: run.adapter, inputs: run.inputs })]);
      notify(`Loaded ${runs.length} ${runs.length === 1 ? 'test' : 'tests'} into the suite for project revision ${project.revision}.`);
    } catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); }
  }
  async function promote(id: string) {
    if (dirty || busy) return;
    setError(''); setBusy(true);
    try {
      const updated = await post<{ revision: number; rechecks: Rechecks }>(`${base}/${encodeURIComponent(id)}/promote`, { expected_revision: project.revision });
      setPromotion(updated.rechecks ? { revision: updated.revision, rechecks: updated.rechecks } : null);
      const first = updated.rechecks?.run_ids[0];
      if (first) setSelected(first);
      await reload(); notify(`Calibration saved to revision ${updated.revision}.`);
    } catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); refresh(); }
  }
  return <div className="analysis-workspace">
    {error && <Notice tone="error">{error}</Notice>}
    {catalogError && <Notice tone="error">{catalogError} <button type="button" className="project-inline-button" onClick={refresh}>Refresh analysis</button></Notice>}
    {!catalog ? !catalogError && <Loading/> : <>
      <EnvironmentMatrix key={project.id} projectId={project.id} revision={project.revision}
        available={canRunMatrix} onVisibilityChange={setMatrixVisible}
        disabled={dirty || busy} onQueue={refresh} revealRequest={matrixRequest}/>
      <section className="project-panel"><header className="project-panel-header"><div>
        <h3>Run an analysis</h3><p>Each run records its inputs and saved project revision {project.revision}. The initial values are examples. For calibration, replace the example data with your own measurements.</p>
      </div></header>
      {adapter ? <form ref={formRef} className="analysis-form" onSubmit={event => { event.preventDefault(); void execute(false); }}>
        <fieldset disabled={busy}><div className="project-form-stack">
          <label className="project-field" data-tour="project-model"><span>Analysis model</span><select value={adapterId} onChange={event => {
            const next = catalog.adapters.find(item => item.id === event.target.value); if (next) choose(next);
          }}>{catalog.adapters.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select><small>{adapter.description}</small></label>
          <label className="project-field"><span>Run label</span><input required maxLength={120} value={runLabel} onChange={event => setRunLabel(event.target.value)}/></label>
          <div className="analysis-inputs">{fields.map(field => {
            const unit = adapter.binding_units?.[field.name];
            const bound = bindings[field.name];
            const units = adapter.binding_accepted_units?.[field.name];
            const parameters = units ? project.parameters.filter(p => units.includes(p.unit.trim())) : project.parameters;
            return <div key={field.name} className={field.type === 'array' || field.type === 'object' ? 'analysis-wide' : ''}>
              {unit && (parameters.length > 0 || bound) && <label className="project-field analysis-binding"><span>{label(field.name)} source ({unit})</span>
                <select value={bound ?? ''} onChange={event => {
                  const value = event.target.value;
                  setBindings(previous => { const next = { ...previous }; if (value) next[field.name] = value; else delete next[field.name]; return next; });
                }}><option value="">Enter a value</option>
                  {bound && !parameters.some(p => p.name === bound) && <option value={bound}>{bound} (check name and unit in this revision)</option>}
                  {parameters.map(p => <option key={p.name} value={p.name}>{p.name} · {p.value} {p.unit}</option>)}
                </select></label>}
              {!bound && <InputControl field={field} draft={draft} update={value => updateField(field.name, value)} project={project}/>}
            </div>;
          })}</div>
          {usesTimeConstant && <p className="small muted">The velocity-servo gain is the reciprocal of the supplied time constant. Use one commanded rotational joint matching the measurement.</p>}
          <details className="analysis-disclosure"><summary data-tour="project-qualification">Model input specification</summary><pre>{JSON.stringify(adapter.schema, null, 2)}</pre></details>
          {dirty && <Notice>Save project changes before starting an analysis.</Notice>}
          <div className="analysis-actions" data-tour="project-run">
            <button className="button primary" type="submit" disabled={dirty}>{busy ? 'Working…' : 'Run analysis'}</button>
            <button className="button secondary" type="button" disabled={suite.length >= 16} onClick={addTest}>Add to suite</button>
          </div>
        </div></fieldset>
      </form> : <p className="card-pad" data-tour="project-model">No analysis models are available for this project type.</p>}
      </section>
      {suite.length > 0 && <section className="project-panel"><header className="project-panel-header"><div><h3>Test suite</h3><p>Run the saved inputs below on project revision {project.revision}.</p></div></header>
        <div className="project-form-stack"><ol className="analysis-suite">{suite.map((test, index) => <li key={index}>
          <div><strong>{test.label}</strong><small>{label(test.adapter)}</small></div>
          <button type="button" disabled={busy} className="project-inline-button" aria-label={`Remove ${test.label}`} onClick={() => setSuite(items => items.filter((_, i) => i !== index))}>Remove</button>
        </li>)}</ol><button type="button" className="button primary" disabled={dirty || busy || suite.some(test => !catalog.adapters.some(item => item.id === test.adapter))} onClick={() => void execute(true)}>Run suite ({suite.length})</button></div>
      </section>}
      {adapterId !== 'packaging_lift' && <ProjectSweeps projectId={project.id} revision={project.revision} adapter={adapterId} draft={draft} bindings={bindings}
        currentTest={currentTest} disabled={dirty || busy} onQueue={refresh} onRun={id => {
          setSelected(id); refresh(); document.getElementById('analysis-history')?.scrollIntoView({ block: 'start' });
        }}/>}
      {promotion && <section className="project-panel">
        <header className="project-panel-header"><div><h3>Calibration rechecks · revision {promotion.revision}</h3>
          <p>{promotion.rechecks.run_ids.length ? 'Inspect each check with the newly calibrated parameter.' : 'No checks on the previous revision referenced this parameter.'}</p>
        </div></header>
        {promotion.rechecks.run_ids.length > 0 && <div className="project-form-stack">
          <ul className="analysis-suite">{promotion.rechecks.run_ids.map(id => <li key={id}><button type="button" className="project-inline-button"
            onClick={() => { setSelected(id); document.getElementById('analysis-history')?.scrollIntoView({ block: 'start' }); }}>
            {catalog.runs.find(run => run.id === id)?.label ?? 'Inspect run'} · {id}
          </button></li>)}</ul>
          {promotion.rechecks.more_available && <Notice>Automatic replay used the 16 most recent distinct checks. Earlier definitions are available in run history for manual replay.</Notice>}
        </div>}
      </section>}
      <AnalysisResults base={base} adapters={catalog.adapters} runs={catalog.runs} selected={selected} select={setSelected}
        refresh={refresh} refreshIndex={refreshIndex} running={busy} jobAction={jobAction} loadSuite={loadSuite} currentRevision={project.revision} promote={dirty ? undefined : promote} reuse={run => {
          const model = catalog.adapters.find(item => item.id === run.adapter);
          if (model) { choose(model, run.definition?.inputs ?? run.inputs, run.label, run.definition?.bindings); formRef.current?.scrollIntoView({ block: 'start' }); }
        }}/>
    </>}
  </div>;
}
