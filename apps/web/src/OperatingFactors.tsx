import { useEffect, useState } from 'react';
import { request } from './api';
import type { OperatingFactor } from './projectTypes';

type Choice = {field: string; label: string; unit: string};

function Levels({factor, change}: {factor: OperatingFactor; change: (values: number[]) => void}) {
  const [draft, setDraft] = useState('');
  const value = Number(draft);
  const valid = draft.trim() !== '' && Number.isFinite(value) && !factor.required_values.includes(value);
  function add() {
    if (valid && factor.required_values.length < 32) {
      change([...factor.required_values, value].sort((a, b) => a - b));
      setDraft('');
    }
  }
  return <div className="project-field"><span>Required operating points{factor.unit && ' (' + factor.unit + ')'}</span>
    {factor.required_values.length > 0 && <div className="analysis-actions">{factor.required_values.map(n =>
      <button type="button" className="button secondary" key={n} aria-label={'Remove required level ' + n}
        onClick={() => change(factor.required_values.filter(x => x !== n))}>{n} ×</button>)}</div>}
    <div className="analysis-actions"><input type="number" step="any" aria-label="New required operating point"
      value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => {
        if (e.key === 'Enter') { e.preventDefault(); add(); }
      }}/>
      <button type="button" className="button secondary" disabled={!valid || factor.required_values.length >= 32} onClick={add}>Add level</button>
    </div>
  </div>;
}

export function OperatingFactors({projectId, factors, onChange}: {
  projectId: string; factors: OperatingFactor[]; onChange: (values: OperatingFactor[]) => void;
}) {
  const [choices, setChoices] = useState<Choice[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let current = true;
    request<{factors: Choice[]}>('/project-campaigns/' + encodeURIComponent(projectId) + '/coverage/catalog')
      .then(data => { if (current) setChoices(data.factors); }, e => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [projectId]);
  function edit(index: number, patch: Partial<OperatingFactor>) {
    onChange(factors.map((item, i) => i === index ? {...item, ...patch} : item));
  }
  return <section className="project-panel"><header className="project-panel-header"><div>
    <h3>Operating conditions to cover</h3><p>Consider loads, contact, surroundings, supply, sensing and wear at the installation site. Map each factor to a model input when available. Campaigns report which declared levels have evidence.</p>
  </div></header><div className="project-form-stack">
    <datalist id="operating-factor-fields">{choices.map(c => <option key={c.field} value={c.field}>{c.label} · {c.unit}</option>)}</datalist>
    {error && <p role="status">Input suggestions unavailable. {error}</p>}
    {factors.map((factor, i) => <fieldset key={i} className="project-editor">
      <legend>{factor.name || 'Operating factor ' + (i + 1)}</legend>
      <div className="project-form-grid">
        <label className="project-field"><span>Factor name</span><input required maxLength={100} value={factor.name}
          placeholder="For example, guide friction" onChange={e => edit(i, {name: e.target.value})}/></label>
        <label className="project-field"><span>Solver input (optional)</span><input list="operating-factor-fields" maxLength={108} value={factor.field}
          placeholder="Leave blank for an unmodeled factor" onChange={e => {
            const field = e.target.value;
            const choice = choices.find(c => c.field === field);
            edit(i, {field, ...(choice && choice.unit !== 'joint units' && !factor.unit && {unit: choice.unit})});
          }}/>{factor.field.startsWith('targets.') && <small>Use the joint’s exact name after targets. Enter rad for rotary joints or m for linear joints.</small>}</label>
        <label className="project-field"><span>Unit</span><input value={factor.unit} maxLength={50}
          onChange={e => edit(i, {unit: e.target.value})}/></label>
        <Levels factor={factor} change={required_values => edit(i, {required_values})}/>
      </div>
      <label className="project-field"><span>Operating requirement and source</span>
        <textarea value={factor.conditions} maxLength={1000} placeholder="Which sites, ranges, combinations or exclusions matter? What measurement or requirement defines them?"
          onChange={e => edit(i, {conditions: e.target.value})}/></label>
      <button type="button" className="project-inline-button" onClick={() => onChange(factors.filter((_, n) => n !== i))}>Remove factor</button>
    </fieldset>)}
    <button type="button" className="button secondary" disabled={factors.length >= 40}
      onClick={() => onChange([...factors, {name:'', field:'', unit:'', conditions:'', required_values:[]}])}>Add operating factor</button>
  </div></section>;
}
