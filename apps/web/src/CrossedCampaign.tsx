import { useRef, useState } from 'react';
import { post } from './api';
import type { RunInput } from './analysisInputs';
import { gridLevels, type AxisChoice, type CrossedDesign } from './campaignAxes';
import { Notice } from './components';

export function CrossedCampaign({projectId, revision, choices, currentTest, disabled, onCreated, design}: {
  projectId: string; revision: number; choices: AxisChoice[]; currentTest: () => RunInput;
  disabled: boolean; onCreated: (id: string) => void; design?: CrossedDesign;
}) {
  const [firstField, setFirst] = useState(design?.axes[0].field ?? '');
  const [secondField, setSecond] = useState(design?.axes[1].field ?? '');
  const [drafts, setDrafts] = useState<Record<string, string>>(() =>
    Object.fromEntries((design?.axes ?? []).map(axis => [axis.field, axis.values.join(', ')])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<{body: string; key: string} | null>(null);
  const first = choices.find(item => item.field === firstField);
  const second = choices.find(item => item.field === secondField);
  let plan: {field: string; values: number[]}[] | undefined;
  let validation = '';
  if (first && second && drafts[first.field]?.trim() && drafts[second.field]?.trim()) {
    try {
      const axes = [first, second].map(choice => ({field: choice.field, values: gridLevels(drafts[choice.field], choice, 8)}));
      if (axes[0].values.length * axes[1].values.length > 16) throw new Error('Reduce the levels to at most 16 combinations.');
      plan = axes;
    } catch (failure) { validation = (failure as Error).message; }
  }
  async function submit() {
    if (!plan || disabled || busy) return;
    setBusy(true); setError('');
    try {
      const body = {...currentTest(), expected_revision: revision, axes: plan};
      const encoded = JSON.stringify(body);
      if (pending.current?.body !== encoded) pending.current = {body: encoded, key: crypto.randomUUID()};
      const result = await post<{suite_id: string}>(`/project-campaigns/${encodeURIComponent(projectId)}/crossed`, body, pending.current.key);
      pending.current = null;
      onCreated(result.suite_id);
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="project-panel" data-tour="campaign-crossed">
    <header className="project-panel-header"><h3>Cross two inputs</h3></header>
    <div className="project-form-stack">
      {choices.length < 2 ? <p>Enter numeric reference values for two model inputs above. Each robot joint target is a separate input.</p> :
        [first, second].map((chosen, index) => <div key={index}>
          <label className="project-field"><span>{index === 0 ? 'First' : 'Second'} input</span>
            <select aria-label={index === 0 ? 'First input' : 'Second input'} value={chosen?.field ?? ''}
              onChange={e => { (index === 0 ? setFirst : setSecond)(e.target.value); setError(''); }}>
              <option value="">Choose an input</option>
              {choices.filter(item => item.field !== (index === 0 ? second : first)?.field).map(item =>
                <option key={item.field} value={item.field}>{item.label} ({item.unit})</option>)}
            </select>
          </label>
          {chosen && <label className="project-field"><span>{chosen.label} levels ({chosen.unit})</span>
            <input value={drafts[chosen.field] ?? ''} placeholder="Separate values with commas" onChange={e => {
              const value = e.target.value;
              setDrafts(prev => ({...prev, [chosen.field]: value})); setError('');
            }}/><small>Include the reference value {chosen.value}. Enter 2–8 levels in increasing order.</small>
          </label>}
        </div>)}
      {validation && <p role="status">{validation}</p>}
      {plan && <p role="status">{plan[0].values.length} × {plan[1].values.length} = {plan[0].values.length * plan[1].values.length} runs on revision {revision}.</p>}
      {error && <Notice tone="error">{error}</Notice>}
      <button className="button primary" type="button" disabled={disabled || busy || !plan} onClick={() => void submit()}>{busy ? 'Queuing…' : 'Run crossed campaign'}</button>
    </div>
  </section>;
}
