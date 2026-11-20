import { useCallback, useEffect, useRef, useState } from 'react';
import { label, post, request } from './api';
import { Loading, Notice } from './components';
import { fieldCaption, fieldText, inputFields, motionModelChoice, referenceHandChoice, rodBoundaryFields, runInputs } from './analysisInputs';
import type { Adapter, InputField, Inputs, RunDetail, RunInput, RunSummary } from './analysisInputs';
import AnalysisResults from './AnalysisResults';
import ProjectSweeps from './ProjectSweeps';
import { CrossedCampaign } from './CrossedCampaign';
import { axisChoices } from './campaignAxes';
import type { CrossedDesign } from './campaignAxes';
import type { SweepCatalog } from './ProjectSweeps';
import EnvironmentMatrix, { MatrixForm } from './EnvironmentMatrix';
import { HelpTutorial } from './HelpTutorial';
import { batchSetupGuide } from './campaignTutorial';
import { projectBatchHref } from './campaignHistory';
import type { Project } from './projectTypes';
import type { ProjectTourCapabilities } from './projectTutorial';

type Catalog = { adapters: Adapter[]; runs: RunSummary[] };
type Rechecks = { suite_id: string | null; run_ids: string[]; previous_run_ids: string[]; more_available: boolean };
const assetFields: Record<string, { kind: string; extension: string; empty?: string }> = {
  model_asset_id: { kind: 'robot_model', extension: '.urdf' },
  controller_asset_id: { kind: 'controller', extension: '.json', empty: 'Use the default controller' },
  cad_asset_id: { kind: 'cad', extension: '.stl' },
  bom_asset_id: { kind: 'bom', extension: '.csv', empty: 'Skip bill of materials' }, training_asset_id: { kind: 'measurements', extension: '.csv' },
  validation_asset_id: { kind: 'measurements', extension: '.csv' },
};
const editorValues = (inputs: Inputs) => Object.fromEntries(Object.entries(inputs).map(([key, value]) => [key, fieldText(value)]));
const errorText = (error: unknown) => error instanceof Error ? error.message : 'The request failed.';

export function InputControl({ field, draft, update, project }: {
  field: InputField; draft: Record<string, string>; update: (value: string) => void; project: Project;
}) {
  const { name, schema, type, required } = field;
  const value = draft[name] ?? '';
  const model = name === 'model_asset_id';
  const filter = assetFields[name];
  const assets = filter ? project.assets.filter(asset => asset.kind === filter.kind &&
    (!filter.extension || asset.filename.toLowerCase().endsWith(filter.extension))) : [];
  return <label className={`project-field ${type === 'array' || type === 'object' ? 'analysis-wide' : ''}`}>
    <span>{model ? 'Robot model to run' : fieldCaption(field)}{(required || model) && ' *'}</span>
    {filter ? <select value={value} required={required || model} disabled={name === 'controller_asset_id' && draft.mode !== 'mujoco_pd'} onChange={event => update(event.target.value)}>
      <option value="">{model ? 'Choose a robot model' : filter.empty ?? 'Select an attached file'}</option>
      {model && <option value={referenceHandChoice}>Built-in example · two-finger reference hand</option>}
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

export default function ProjectAnalysis({ project, dirty, reload, notify, matrixRequest, onTourCapabilities, campaignSetup = false, crossedSuite }: {
  project: Project; dirty: boolean; reload: () => Promise<void>; notify: (message: string) => void; matrixRequest: number;
  onTourCapabilities: (capabilities: ProjectTourCapabilities | null) => void;
  campaignSetup?: boolean;
  crossedSuite?: string | null;
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
  const [suiteName, setSuiteName] = useState('');
  const [batchKind, setBatchKind] = useState<'suite' | 'sweep' | 'crossed' | 'matrix'>(project.robot_template === 'packaging_lift_v1' ? 'matrix' : 'suite');
  const [sweepCatalog, setSweepCatalog] = useState<SweepCatalog | null>(null);
  const [sweepError, setSweepError] = useState('');
  const [savedDesign, setSavedDesign] = useState<CrossedDesign>();
  const [setupError, setSetupError] = useState('');
  const loadedDesign = useRef(false);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [promotion, setPromotion] = useState<{ revision: number; rechecks: Rechecks } | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  const lastSubmission = useRef<{ body: string; key: string } | null>(null);
  const draftsByModel = useRef(new Map<string, { values: Record<string, string>; bound: Record<string, string>; title: string }>());
  const refresh = () => setRefreshIndex(index => index + 1);
  const isReferenceHand = project.robot_source === 'supported' && project.robot_template === 'two_finger_hand_v1';
  const choose = useCallback((adapter: Adapter, inputs?: Inputs, title = adapter.id === 'calibration' ? `${adapter.label} (example measurements)` : adapter.label, bound: Record<string, string> = {}) => {
    const next = editorValues(inputs ?? adapter.example);
    if (!inputs) for (const name of Object.keys(assetFields)) delete next[name];
    if (adapter.id === 'robot_motion') next.model_asset_id = motionModelChoice(inputs, isReferenceHand);
    setAdapterId(adapter.id); setDraft(next); setRunLabel(title); setBindings(bound);
  }, [isReferenceHand]);
  useEffect(() => {
    if (!campaignSetup) return;
    let current = true;
    void request<SweepCatalog>(`/projects/${encodeURIComponent(project.id)}/sweeps/catalog`)
      .then(data => { if (current) { setSweepCatalog(data); setSweepError(''); } })
      .catch((failure: Error) => { if (current) setSweepError(failure.message); });
    return () => { current = false; };
  }, [campaignSetup, project.id, project.revision, refreshIndex]);
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
  const sweepModels = catalog?.adapters.filter(item => Boolean(sweepCatalog?.adapters[item.id]?.length)) ?? [];
  const lift = catalog?.adapters.find(item => item.id === 'packaging_lift');
  const crossedModels = lift ? [...sweepModels, lift] : sweepModels;
  const mode = ((batchKind === 'matrix' && !canRunMatrix) || (batchKind === 'sweep' && !sweepModels.length)
    || (batchKind === 'crossed' && !crossedModels.length)) ? 'suite' : batchKind;
  const sweepSetup = campaignSetup && mode === 'sweep';
  const crossedSetup = campaignSetup && mode === 'crossed';
  const gridSetup = sweepSetup || crossedSetup;
  const matrixSetup = campaignSetup && mode === 'matrix';
  const modelMissing = adapterId === 'robot_motion' && !draft.model_asset_id;
  const selectable = crossedSetup ? crossedModels : sweepSetup ? sweepModels : catalog?.adapters ?? [];
  const modelSelected = Boolean(adapter && selectable.some(item => item.id === adapter.id));
  const openBatch = (id: string) => { window.location.hash = projectBatchHref(project.id, id); };
  useEffect(() => {
    if (!campaignSetup || !crossedSuite || !catalog || !sweepCatalog || loadedDesign.current) return;
    let current = true;
    void request<{crossed_design?: CrossedDesign}>(`/project-campaigns/${encodeURIComponent(project.id)}/${encodeURIComponent(crossedSuite)}`)
      .then(result => {
        if (!current) return;
        const design = result.crossed_design;
        const model = catalog.adapters.find(item => item.id === design?.adapter);
        if (!design || !model) throw new Error('The saved crossed setup is unavailable for this revision.');
        choose(model, design.inputs, design.label, design.bindings);
        loadedDesign.current = true;
        setSavedDesign(design); setBatchKind('crossed'); setSetupError('');
      }).catch((failure: Error) => { if (current) setSetupError(failure.message); });
    return () => { current = false; };
  }, [campaignSetup, crossedSuite, catalog, sweepCatalog, project.id, choose]);
  function changeAdapter(next: Adapter) {
    if (adapter) draftsByModel.current.set(adapter.id, { values: draft, bound: bindings, title: runLabel });
    const saved = draftsByModel.current.get(next.id);
    if (!saved) { choose(next); return; }
    setAdapterId(next.id); setDraft(saved.values); setBindings(saved.bound); setRunLabel(saved.title);
  }
  const velocityServo = adapterId === 'robot_motion' && draft.mode === 'velocity_servo';
  const usesTimeConstant = velocityServo && Boolean(bindings.time_constant_s || draft.time_constant_s?.trim());
  const rightEnd = adapterId === 'thermal_rod' && adapter?.schema.properties?.right_film_coefficient_w_m2k
    ? rodBoundaryFields(draft, bindings) : null;
  const fields = adapter ? inputFields(adapter).filter(field =>
    !rightEnd?.hidden.includes(field.name) &&
    !(adapterId === 'robot_motion' && field.name === 'time_constant_s' && !velocityServo) &&
    !(usesTimeConstant && field.name === 'gain_per_s')).map(field =>
      rightEnd?.required.includes(field.name) ? { ...field, required: true } : field) : [];
  const sweepDraft = rightEnd ? Object.fromEntries(Object.entries(draft).filter(([key]) => !rightEnd.hidden.includes(key))) : draft;
  function updateField(name: string, value: string) {
    setDraft(previous => {
      const next = { ...previous, [name]: value };
      if (adapter?.id === 'robot_motion' && next.mode !== 'mujoco_pd') delete next.controller_asset_id;
      return next;
    });
  }
  function currentTest(): RunInput {
    if (!adapter || !runLabel.trim()) throw new Error('Choose an analysis and enter a run label.');
    const inputs = runInputs(adapter.id, fields.filter(field => !bindings[field.name]), draft);
    const activeBindings = Object.fromEntries(fields.filter(field => bindings[field.name]).map(field => [field.name, bindings[field.name]]));
    return { label: runLabel.trim(), adapter: adapter.id, inputs, ...(Object.keys(activeBindings).length ? { bindings: activeBindings } : {}) };
  }
  function addTest() {
    if (suite.length >= 16 || !formRef.current?.reportValidity()) return;
    try { const test = currentTest(); setSuite(items => [...items, test]); setError(''); }
    catch (failure) { setError(errorText(failure)); }
  }
  async function execute(asSuite: boolean) {
    if (busy || dirty || (campaignSetup && (!asSuite || !suiteName.trim() || !suite.length))) return;
    setError(''); setBusy(true);
    try {
      const body = asSuite ? { expected_revision: project.revision, tests: suite, ...(campaignSetup && { label: suiteName.trim() }) } : { ...currentTest(), expected_revision: project.revision };
      const encoded = JSON.stringify(body);
      if (lastSubmission.current?.body !== encoded) lastSubmission.current = { body: encoded, key: crypto.randomUUID() };
      if (asSuite) {
        const data = await post<{ suite_id: string; runs: RunSummary[] }>(`${base}-suite`, body, lastSubmission.current.key);
        setSuite([]); setSelected(data.runs[0]?.id ?? '');
        const failures = data.runs.filter(run => run.error || run.status === 'failed' || run.status === 'error');
        if (failures.length) setError(failures.map(run => `${run.label}: ${run.error ?? run.status}`).join('\n'));
        notify(`Queued ${data.runs.length} ${data.runs.length === 1 ? 'run' : 'runs'}. Follow progress in run history.`);
        if (campaignSetup) openBatch(data.suite_id);
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
      {campaignSetup && <section className="project-panel"><header className="project-panel-header"><div>
        <h3>Campaign setup</h3><p>Build a batch for {project.name} on revision {project.revision}.</p></div>
        <HelpTutorial title="Batch setup tutorial" steps={batchSetupGuide(mode, modelSelected)}/></header>
        <div className="project-form-stack"><label className="project-field" data-tour="campaign-batch-kind"><span>Campaign type</span>
          <select value={mode} onChange={event => setBatchKind(event.target.value as typeof batchKind)}>
            <option value="suite">Test suite</option>
            {sweepModels.length > 0 && <option value="sweep">Parameter sweep</option>}
            {crossedModels.length > 0 && <option value="crossed">Cross two inputs</option>}
            {canRunMatrix && <option value="matrix">Environment matrix</option>}
          </select><small>{{suite: 'Build up to 16 named tests. Each test keeps its own model and inputs.',
            sweep: 'Vary one model input and compare the results against a reference value.',
            crossed: 'Test every combination of two inputs, up to 16 runs. Other inputs stay at the reference settings.',
            matrix: 'Cross parcel masses with packing-head forces and choose a reference condition.'}[mode]}</small>
        </label>
        {sweepError && <Notice tone="warning">Sweep options could not load. {sweepError} <button type="button" className="project-inline-button" onClick={refresh}>Retry</button></Notice>}
        {crossedSuite && !savedDesign && <Notice tone={setupError ? 'warning' : undefined}>{setupError || 'Loading saved crossed setup…'}</Notice>}
        {savedDesign && <p>Loaded settings from revision {savedDesign.expected_revision}. New runs use revision {project.revision}.</p>}
        <a className="text-link" href={'#/projects/' + encodeURIComponent(project.id) + '?tab=phases'}>Review task phases before running this campaign</a>
        {dirty && <Notice>Save the project changes before starting a campaign.</Notice>}
        </div>
      </section>}
      {!campaignSetup && <EnvironmentMatrix key={project.id} projectId={project.id} revision={project.revision}
        available={canRunMatrix} onVisibilityChange={setMatrixVisible}
        disabled={dirty || busy} onQueue={refresh} revealRequest={matrixRequest}/>}
      {campaignSetup && canRunMatrix && <section hidden={!matrixSetup} className="project-panel">
        <header className="project-panel-header"><div><h3>Environment matrix</h3><p>The lift moves to 150 mm by 1 s and holds against the downward force until 2 s. Its arrival and hold tolerance is 10 mm.</p></div></header>
        <div className="project-form-stack"><MatrixForm revision={project.revision} disabled={dirty || busy}
          base={`/projects/${encodeURIComponent(project.id)}/environment-matrices`}
          onSaved={record => openBatch(record.suite_id)} tour="campaign-matrix-values"/></div>
      </section>}
      <section className="project-panel" hidden={matrixSetup}><header className="project-panel-header"><div>
        <h3>{campaignSetup ? gridSetup ? 'Reference test' : 'Configure a test' : 'Run an analysis'}</h3><p>Each run records its inputs and saved project revision {project.revision}. The initial values are examples. For calibration, replace the example data with your own measurements.</p>
      </div>{!campaignSetup && <a className="button secondary" href={`#/projects/${encodeURIComponent(project.id)}/analysis?setup=campaign`}>New campaign</a>}</header>
      {adapter ? <form ref={formRef} className="analysis-form" onSubmit={event => { event.preventDefault(); if (!campaignSetup) void execute(false); else if (!gridSetup) addTest(); }}>
        <fieldset disabled={busy}><div className="project-form-stack">
          <label className="project-field" data-tour="project-model"><span>Analysis model</span><select value={modelSelected ? adapterId : ''} onChange={event => {
            const next = selectable.find(item => item.id === event.target.value); if (next) changeAdapter(next);
          }}>{!modelSelected && <option value="">Choose a supported model</option>}{selectable.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select><small>{modelSelected && adapter.description}</small></label>
          {modelSelected && <><label className="project-field"><span>{crossedSetup ? 'Campaign name' : sweepSetup ? 'Sweep name' : 'Run label'}</span><input required maxLength={gridSetup ? 100 : 120} value={runLabel} onChange={event => setRunLabel(event.target.value)}/></label>
          {rightEnd && <label className="project-field"><span>Right end boundary condition</span>
            <select value={rightEnd.fluid ? 'fluid' : 'fixed'} onChange={event => updateField('rightBoundaryChoice', event.target.value)}>
              <option value="fixed">Prescribed surface temperature</option>
              <option value="fluid">Heat exchange with ambient fluid</option>
            </select></label>}
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
          {!gridSetup && <div className="analysis-actions" data-tour="project-run">
            {!campaignSetup && <button className="button primary" type="submit" disabled={dirty}>{busy ? 'Working…' : 'Run analysis'}</button>}
            <button className="button secondary" type="button" disabled={suite.length >= 16} onClick={addTest}>Add to suite</button>
          </div>}</>}
        </div></fieldset>
      </form> : <p className="card-pad" data-tour="project-model">No analysis models are available for this project type.</p>}
      </section>
      {(campaignSetup || suite.length > 0) && <section hidden={campaignSetup && mode !== 'suite'} className="project-panel" data-tour="campaign-suite-review"><header className="project-panel-header"><div><h3>Test suite</h3><p>Run the saved inputs below on project revision {project.revision}.</p></div></header>
        <div className="project-form-stack">
          {campaignSetup && <label className="project-field"><span>Campaign name</span><input required maxLength={120} value={suiteName} onChange={event => setSuiteName(event.target.value)}/></label>}
          {!suite.length && <p className="small muted">Configure a test above and choose Add to suite.</p>}
          <ol className="analysis-suite">{suite.map((test, index) => <li key={index}>
          <div><strong>{test.label}</strong><small>{label(test.adapter)}</small></div>
          <button type="button" disabled={busy} className="project-inline-button" aria-label={`Remove ${test.label}`} onClick={() => setSuite(items => items.filter((_, i) => i !== index))}>Remove</button>
        </li>)}</ol><button type="button" className="button primary" disabled={dirty || busy || !suite.length || (campaignSetup && !suiteName.trim()) || suite.some(test => !catalog.adapters.some(item => item.id === test.adapter))} onClick={() => void execute(true)}>Run suite ({suite.length})</button></div>
      </section>}
      {crossedSetup && modelSelected && <CrossedCampaign key={project.id + adapterId + (savedDesign?.adapter ?? '')} projectId={project.id} revision={project.revision}
        choices={axisChoices(sweepCatalog?.adapters[adapterId] ?? Object.entries(lift?.binding_units ?? {}).map(([field, unit]) =>
          ({field, unit, label: label(field)})), sweepDraft, bindings)} currentTest={currentTest}
        design={adapterId === savedDesign?.adapter ? savedDesign : undefined} disabled={dirty || busy || modelMissing} onCreated={openBatch}/>}
      {(!campaignSetup ? adapterId !== 'packaging_lift' : sweepCatalog && sweepModels.some(item => item.id === adapterId)) && <div hidden={campaignSetup && !sweepSetup}>
        <ProjectSweeps projectId={project.id} revision={project.revision} adapter={adapterId} draft={sweepDraft} bindings={bindings}
        currentTest={currentTest} disabled={dirty || busy || modelMissing} setupCatalog={campaignSetup ? sweepCatalog ?? undefined : undefined}
        onCreated={campaignSetup ? openBatch : undefined} onQueue={refresh} onRun={id => {
          setSelected(id); refresh(); document.getElementById('analysis-history')?.scrollIntoView({ block: 'start' });
        }}/></div>}
      {!campaignSetup && promotion && <section className="project-panel">
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
      {!campaignSetup && <AnalysisResults base={base} adapters={catalog.adapters} runs={catalog.runs} selected={selected} select={setSelected}
        refresh={refresh} refreshIndex={refreshIndex} running={busy} jobAction={jobAction} loadSuite={loadSuite} currentRevision={project.revision} promote={dirty ? undefined : promote} reuse={run => {
          const model = catalog.adapters.find(item => item.id === run.adapter);
          if (model) { choose(model, run.definition?.inputs ?? run.inputs, run.label, run.definition?.bindings); formRef.current?.scrollIntoView({ block: 'start' }); }
        }}/>}
    </>}
  </div>;
}
