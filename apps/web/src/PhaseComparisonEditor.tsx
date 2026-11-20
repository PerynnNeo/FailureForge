import { useEffect, useState } from 'react';
import { request } from './api';
import { fieldText, inputFields, motionModelChoice, rodBoundaryFields, runInputs } from './analysisInputs';
import type { Adapter, Inputs, RunDetail, RunSummary } from './analysisInputs';
import { InputControl } from './ProjectAnalysis';
import { Notice } from './components';
import type { PhaseTest, Project } from './projectTypes';

export type PhaseCatalog = { adapters: Adapter[]; runs: RunSummary[] };

function referenceDraft(model: Adapter, project: Project, inputs?: Inputs) {
  const values = Object.fromEntries(Object.entries(inputs ?? model.example).map(([key, value]) => [key, fieldText(value)]));
  if (model.id === 'robot_motion') {
    values.model_asset_id = motionModelChoice(inputs, project.robot_template === 'two_finger_hand_v1');
  }
  return values;
}

function axes(model: Adapter, draft: Record<string, string>) {
  return Object.entries(model.phase_fields ?? {}).flatMap(([field, label]) => {
    if (field !== 'targets.*') return [{ field, label }];
    try {
      const targets = JSON.parse(draft.targets ?? '{}');
      return Object.entries(targets).flatMap(([joint, value]) =>
        typeof value === 'number' ? [{ field: 'targets.' + joint, label: 'Joint target · ' + joint }] : []);
    } catch { return []; }
  });
}

export function PhaseComparisonEditor({ project, catalog, initial, preferred, onChange }: {
  project: Project; catalog: PhaseCatalog; initial?: PhaseTest | null;
  preferred?: { adapter?: string; field?: string }; onChange: (test: PhaseTest | null) => void;
}) {
  const models = catalog.adapters.filter(item => Object.keys(item.phase_fields ?? {}).length > 0);
  const [modelId, setModel] = useState(initial?.adapter ?? preferred?.adapter ?? '');
  const model = models.find(item => item.id === modelId);
  const [source, setSource] = useState('');
  const [draft, setDraft] = useState<Record<string, string>>(() => model ? referenceDraft(model, project, initial?.reference_inputs) : {});
  const [field, setField] = useState(initial?.field ?? preferred?.field ?? '');
  const [changed, setChanged] = useState(initial ? String(initial.changed_value) : '');
  const [confirmed, setConfirmed] = useState(Boolean(initial));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [referenceError, setReferenceError] = useState('');
  const options = model ? axes(model, draft) : [];
  const rightEnd = model?.id === 'thermal_rod' ? rodBoundaryFields(draft, {}) : null;
  const fields = model ? inputFields(model).filter(input =>
    !rightEnd?.hidden.includes(input.name) && !(input.name === 'time_constant_s' && draft.mode !== 'velocity_servo') &&
    !(input.name === 'gain_per_s' && draft.mode === 'velocity_servo' && draft.time_constant_s)).map(input =>
      rightEnd?.required.includes(input.name) ? { ...input, required: true } : input) : [];
  const runs = catalog.runs.filter(run => run.project_revision === project.revision && run.adapter === model?.id && run.status === 'completed');
  useEffect(() => {
    if (!source || !model) return;
    let current = true;
    setLoading(true); setReferenceError('');
    void request<RunDetail>('/projects/' + encodeURIComponent(project.id) + '/analysis/' + encodeURIComponent(source)).then(run => {
      if (!current) return;
      if (run.status !== 'completed' || run.error || run.assessment_error) throw new Error('Choose a successfully completed reference.');
      setDraft(referenceDraft(model, project, run.inputs));
    }).catch((failure: Error) => { if (current) setReferenceError(failure.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [source, model, project]);
  useEffect(() => {
    if (!confirmed || !model || !field || !changed.trim() || loading || referenceError) {
      onChange(null); setError(''); return;
    }
    try {
      const inputs = runInputs(model.id, fields, draft);
      const base = field.startsWith('targets.') ? (inputs.targets as Inputs | undefined)?.[field.slice(8)] : inputs[field];
      if (typeof base !== 'number') throw new Error('Enter a numeric reference value for the condition you are varying.');
      const alternative = Number(changed);
      if (!Number.isFinite(alternative) || base === alternative) throw new Error('Enter a changed value that differs from the reference.');
      if (!options.some(option => option.field === field)) throw new Error('Choose an available operating input.');
      setError('');
      onChange({adapter: model.id, field, reference_inputs: inputs, changed_value: alternative});
    } catch (failure) { onChange(null); setError((failure as Error).message); }
    // Fields and options are derived entirely from model and draft.
  }, [model, field, changed, draft, confirmed, loading, referenceError, onChange]);
  const chooseModel = (id: string) => {
    const selected = models.find(item => item.id === id);
    setModel(id); setSource(''); setField(''); setChanged(''); setDraft(selected ? referenceDraft(selected, project) : {});
    setConfirmed(false); setLoading(false); setReferenceError('');
  };
  return <fieldset className="phase-model"><legend>Reference and changed condition</legend>
    <label className="project-field"><span>Simulation model</span><select value={model?.id ?? ''} required onChange={e => chooseModel(e.target.value)}>
      <option value="">Choose a model</option>{models.map(item => <option value={item.id} key={item.id}>{item.label}</option>)}
    </select></label>
    {model && <>
      <p>{model.description}</p>
      <label className="project-field"><span>Reference settings</span><select value={source} onChange={e => {
        const id = e.target.value;
        setSource(id); setConfirmed(false); setReferenceError('');
        if (!id) { setDraft(referenceDraft(model, project)); setLoading(false); }
      }}><option value="">{initial?.adapter === model.id ? 'Review the saved settings' : 'Enter settings from model example'}</option>
        {runs.map(run => <option key={run.id} value={run.id}>{run.label} · {run.id.slice(-8)}</option>)}</select>
        <small>Check the reference settings against your prototype before running.</small></label>
      {referenceError && <Notice tone="error">{referenceError}</Notice>}
      {loading && <p role="status">Loading reference settings…</p>}
      <fieldset disabled={loading} className="phase-model-inputs">
        {rightEnd && <label className="project-field"><span>Right end boundary</span>
          <select value={rightEnd.fluid ? 'fluid' : 'fixed'} onChange={e => { setConfirmed(false); setDraft({...draft, rightBoundaryChoice:e.target.value}); }}>
            <option value="fixed">Fixed surface temperature</option><option value="fluid">Heat exchange with surrounding fluid</option>
          </select></label>}
        {fields.map(input => <InputControl key={input.name} field={input} draft={draft} project={project}
          update={value => { setConfirmed(false); setDraft({...draft, [input.name]:value}); }}/>)}
      </fieldset>
      <div className="phase-model-inputs">
        <label className="project-field"><span>Input to vary</span><select value={field} required onChange={e => {setField(e.target.value); setConfirmed(false);}}>
          <option value="">Choose an operating input</option>{options.map(option => <option key={option.field} value={option.field}>{option.label}</option>)}
        </select></label>
        <label className="project-field"><span>Changed value</span><input type="number" step="any" required value={changed}
          onChange={e => {setChanged(e.target.value); setConfirmed(false);}}/><small>Use the same unit as the reference input.</small></label>
      </div>
      <label className="phase-check"><input type="checkbox" required disabled={loading || Boolean(referenceError)} checked={confirmed}
        onChange={e => setConfirmed(e.target.checked)}/>I checked that the selected input represents this condition and confirmed both sets of settings.</label>
      {error && <Notice tone="error">{error}</Notice>}
    </>}
  </fieldset>;
}
