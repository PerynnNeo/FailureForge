import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { post, request } from './api';
import { Icon, Notice } from './components';
import { projectBatchHref } from './campaignHistory';
import { phaseStarters, phaseQuestions, conditionSuggestions } from './phaseDiscovery';
import { conditionStatusLabels } from './projectTypes';
import type { ConditionStatus, PhaseCondition, PhaseTest, Project, TaskPhase } from './projectTypes';
import { PhaseComparisonEditor } from './PhaseComparisonEditor';
import type { PhaseCatalog } from './PhaseComparisonEditor';
import './taskPhases.css';

const freshId = () => crypto.randomUUID();
type Suggestion = ReturnType<typeof conditionSuggestions>[number];
const newCondition = (answer: string, question: string): PhaseCondition =>
  ({ id:freshId(), answer, question, status:'awaiting_data', reason:'', next_step:'' });

function AssessmentEditor({ original, preferred, project, catalog, onCommit, cancel }: {
  original: PhaseCondition; preferred?: Suggestion; project: Project; catalog: PhaseCatalog | null;
  onCommit: (condition: PhaseCondition) => void; cancel: () => void;
}) {
  const [value, setValue] = useState(original);
  const [test, setTest] = useState<PhaseTest | null>(original.test ?? null);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!value.answer.trim() || !value.reason.trim() || !value.next_step.trim() || (value.status === 'modeled' && !test)) return;
    onCommit({...value, test:value.status === 'modeled' ? test : null});
  }
  return <form className="phase-assessment" onSubmit={submit}>
    <label className="project-field"><span>Engineer’s answer</span><textarea required maxLength={500} value={value.answer}
      onChange={e => setValue({...value, answer:e.target.value})}/></label>
    <label className="project-field"><span>Condition name</span><input maxLength={120} value={value.subject ?? ''}
      placeholder="Optional short name" onChange={e => setValue({...value,subject:e.target.value})}/></label>
    <label className="project-field"><span>Condition status</span>
      <select value={value.status} onChange={e => {
        const status = e.target.value as ConditionStatus;
        setValue({...value, status, reason:status === original.status ? original.reason : '',
          next_step:status === original.status ? original.next_step :
            status === 'modeled' ? 'Run the reference and changed settings, then compare their recorded response.' : ''});
      }}>
        {Object.entries(conditionStatusLabels).map(([status,title]) => <option key={status} value={status}>{title}</option>)}
      </select></label>
    {value.status === 'modeled' && (catalog ? <PhaseComparisonEditor project={project} catalog={catalog} initial={original.test}
      preferred={preferred} onChange={setTest}/> : <p role="status">The available simulation models must load before you can attach a comparison.</p>)}
    <label className="project-field"><span>Reason for this status</span><textarea value={value.reason} required maxLength={1000}
      placeholder={value.status === 'modeled' ? 'How does the input you are changing represent this condition?' :
        'Which effect, measurement or solver input determines this status?'} onChange={e => setValue({...value,reason:e.target.value})}/></label>
    <label className="project-field"><span>Next action</span><textarea value={value.next_step} required maxLength={1000}
      placeholder="Name the comparison, bench check or missing measurement." onChange={e => setValue({...value,next_step:e.target.value})}/></label>
    <div className="phase-actions"><button className="button primary" type="submit"
      disabled={!value.reason.trim() || !value.next_step.trim() || (value.status === 'modeled' && !test)}>Keep assessment</button>
      <button className="project-inline-button" type="button" onClick={cancel}>Cancel</button></div>
  </form>;
}

function ConditionCard({ condition, phase, dirty, project, edit, onRemove }: {
  condition: PhaseCondition; phase: TaskPhase; dirty: boolean; project: Project;
  edit: () => void; onRemove: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const key = useRef<{ revision: number; value: string } | null>(null);
  async function run() {
    if (busy || dirty || !condition.test || condition.status !== 'modeled') return;
    setBusy(true); setError('');
    if (key.current?.revision !== project.revision) key.current = {revision:project.revision,value:freshId()};
    try {
      const receipt = await post<{suite_id: string; runs: {id: string}[]}>('/projects/' + encodeURIComponent(project.id) +
        '/task-phases/' + encodeURIComponent(phase.id) + '/conditions/' + encodeURIComponent(condition.id) + '/run',
      {expected_revision:project.revision}, key.current.value);
      window.location.hash = projectBatchHref(project.id, receipt.suite_id, receipt.runs[1]?.id);
    } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }
  return <article className="phase-condition">
    <div className="phase-condition-title"><h5>{condition.subject || condition.answer}</h5>
      <span className={'phase-status status-' + condition.status}>{conditionStatusLabels[condition.status]}</span></div>
    {condition.subject && condition.subject !== condition.answer && <p className="phase-quote">{condition.answer}</p>}
    {condition.question && <small>Asked · {condition.question}</small>}
    <dl><dt>Reason</dt><dd>{condition.reason}</dd><dt>Next action</dt><dd>{condition.next_step}</dd></dl>
    {condition.test && <p className="phase-controls"><strong>Comparison</strong> {condition.test.field} → {condition.test.changed_value}</p>}
    <div className="phase-actions">
      {condition.status === 'modeled' && <button className="button secondary" type="button" onClick={() => void run()}
        disabled={busy || dirty}>{busy ? 'Submitting…' : 'Run comparison'}</button>}
      <button type="button" className="project-inline-button" disabled={busy} onClick={edit}>Edit condition</button>
      <button type="button" className="project-inline-button" disabled={busy} onClick={onRemove}>Remove</button>
    </div>
    {condition.test && dirty && <small>Save project changes to run this comparison.</small>}
    {error && <Notice tone="error">{error}</Notice>}
  </article>;
}

function PhaseInterview({ project, phase, catalog, dirty, update }: {
  project: Project; phase: TaskPhase; catalog: PhaseCatalog | null; dirty: boolean; update: (phase: TaskPhase) => void;
}) {
  const [answer, setAnswer] = useState('');
  const [editing, setEditing] = useState<PhaseCondition | null>(null);
  const questions = phaseQuestions(project, phase.name);
  const suggestions = answer.trim() ? conditionSuggestions(project, answer) : [];
  const room = 24 - phase.conditions.length;
  const recorded = phase.conditions.filter(c => c.answer === answer.trim() && c.question === phase.question);
  const offered = suggestions.filter(s => !recorded.some(c => c.subject === s.label));
  function keepSuggestions(items: Suggestion[]) {
    if (!items.length || items.length > room || !answer.trim()) return;
    const added = items.map(s => ({...newCondition(answer.trim(), phase.question), subject:s.label, status:s.status, reason:s.reason, next_step:s.next_step}));
    update({...phase,conditions:[...phase.conditions, ...added]});
  }
  function commit(condition: PhaseCondition) {
    const existing = phase.conditions.some(item => item.id === condition.id);
    if (!existing && !room) return;
    update({...phase,conditions:existing ? phase.conditions.map(item => item.id === condition.id ? condition : item) : [...phase.conditions, condition]});
    setEditing(null);
  }
  return <section className="phase-interview" aria-label={'Review phase ' + phase.name}>
    <header><h4>{phase.name}</h4>
      <details className="phase-settings"><summary>Phase settings</summary>
        <label className="project-field"><span>Phase name</span><input maxLength={100} value={phase.name}
          onChange={e => update({...phase,name:e.target.value})}/></label>
        <label className="project-field"><span>Question for this phase</span><textarea maxLength={600} value={phase.question}
          onChange={e => update({...phase,question:e.target.value})}/></label>
      </details>
    </header>
    <div className="phase-question">
      <h5>{phase.question || 'What changes during this phase?'}</h5>
      {questions.some(q => q !== phase.question) && <details><summary>Choose another question</summary>
        <div className="phase-questions">{questions.filter(q => q !== phase.question).map(q => <button type="button" key={q}
          className="project-inline-button" onClick={() => update({...phase,question:q})}>{q}</button>)}</div></details>}
      <label className="project-field"><span>Engineer’s answer</span><textarea value={answer} maxLength={500} rows={2}
        placeholder="Describe what might vary in actual use." onChange={e => setAnswer(e.target.value)}/></label>
      {answer.trim() && <div className="phase-suggestions">
        {offered.map(s => <article className="phase-suggestion" key={s.label}>
          <div className="phase-condition-title"><strong>{s.label}</strong><span className={'phase-status status-' + s.status}>{conditionStatusLabels[s.status]}</span></div>
          <p>{s.reason}</p><p><strong>Next action</strong> {s.next_step}</p>
          <button type="button" className="button secondary" disabled={!room} onClick={() => keepSuggestions([s])}>Add this condition</button>
        </article>)}
        <div className="phase-actions">
          {offered.length > 1 && <button type="button" className="button secondary" disabled={offered.length > room}
            onClick={() => keepSuggestions(offered)}>Add all {offered.length} conditions</button>}
          <button type="button" className="project-inline-button" disabled={!room || Boolean(editing)}
            onClick={() => setEditing(newCondition(answer.trim(), phase.question))}>Write my own assessment</button>
          {recorded.length > 0 && <button type="button" className="project-inline-button" disabled={Boolean(editing)}
            onClick={() => setAnswer('')}>Start next answer</button>}
        </div>
        {recorded.length > 0 && <small role="status">{recorded.length} {recorded.length === 1 ? 'condition' : 'conditions'} recorded from this answer.
          You can add another effect in your own words.</small>}
      </div>}
    </div>
    {Boolean(phase.conditions.length || editing) && <div className="phase-records"><h4>Recorded conditions ({phase.conditions.length})</h4>
      {phase.conditions.map(condition => editing?.id === condition.id ? <AssessmentEditor key={condition.id}
        original={editing} project={project} catalog={catalog} onCommit={commit} cancel={() => setEditing(null)}
        preferred={conditionSuggestions(project, condition.answer).find(s => s.label === condition.subject)}/> :
        <ConditionCard key={condition.id} condition={condition} phase={phase} project={project} dirty={dirty}
          edit={() => setEditing(condition)} onRemove={() => update({...phase,conditions:phase.conditions.filter(c => c.id !== condition.id)})}/>)}
      {editing && !phase.conditions.some(c => c.id === editing.id) && <AssessmentEditor key={editing.id} original={editing}
        project={project} catalog={catalog} onCommit={commit} cancel={() => setEditing(null)}/>}
    </div>}
  </section>;
}

export function TaskPhases({ project, phases, dirty, update }: {
  project: Project; phases: TaskPhase[]; dirty: boolean; update: (phases: TaskPhase[]) => void;
}) {
  const [selectedId, select] = useState('');
  const [custom, setCustom] = useState('');
  const [catalog, setCatalog] = useState<PhaseCatalog | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const selected = phases.find(p => p.id === selectedId) ?? phases[0];
  const starters = phaseStarters(project).filter(s => !phases.some(p => p.name.toLowerCase() === s.name.toLowerCase()));
  useEffect(() => {
    let current = true;
    void request<PhaseCatalog>('/projects/' + encodeURIComponent(project.id) + '/analysis').then(data => {
      if (current) {setCatalog(data); setError('');}
    }).catch((failure: Error) => { if (current) setError(failure.message); });
    return () => {current = false;};
  }, [project.id, project.revision, attempt]);
  function addPhase(name: string, question: string) {
    const title = name.trim();
    if (!title || phases.length >= 16) return;
    const phase = {id:freshId(), name:title, question, conditions:[]};
    update([...phases, phase]); select(phase.id); setCustom('');
  }
  return <section className="project-panel task-phases" data-tour="project-task-phases">
    <header className="project-panel-header"><div><h3>Task phases</h3>
      <p>Walk through the task with someone who operates the prototype. Record what changes in each phase and how to test it.</p></div></header>
    <div className="project-form-stack">
      {phases.length > 0 && <nav className="phase-steps" aria-label="Saved task phases">{phases.map(phase =>
        <button type="button" key={phase.id} aria-current={phase.id === selected?.id ? 'step' : undefined}
          onClick={() => select(phase.id)}>{phase.name || 'Unnamed phase'} <small>{phase.conditions.length}</small></button>)}</nav>}
      <details className="phase-add" open={phases.length ? undefined : true} key={phases.length ? 'existing' : 'empty'}>
        <summary>{phases.length ? 'Add another phase' : 'Choose a starting phase'}</summary>
        <div className="phase-starters">{starters.map(s => <button type="button" key={s.name} className="button secondary"
          disabled={phases.length >= 16} onClick={() => addPhase(s.name, s.question)}><Icon name="plus" size={14}/>{s.name}</button>)}</div>
        <div className="phase-custom"><label className="project-field"><span>Custom phase name</span><input value={custom} maxLength={100}
          placeholder="An action in your prototype’s task" onChange={e => setCustom(e.target.value)}/></label>
          <button type="button" className="button secondary" disabled={!custom.trim() || phases.length >= 16} onClick={() =>
            addPhase(custom, phaseQuestions(project, custom.trim())[0] || 'What can change while the prototype performs this phase?')}>Add phase</button></div>
      </details>
      {error && <Notice tone="warning">Simulation models could not load. {error} <button className="project-inline-button" type="button"
        onClick={() => setAttempt(n => n + 1)}>Retry</button></Notice>}
      {phases.map(phase => <div key={phase.id} hidden={phase.id !== selected?.id}><PhaseInterview project={project} phase={phase}
        catalog={catalog} dirty={dirty} update={next => update(phases.map(item => item.id === next.id ? next : item))}/></div>)}
      {selected && !selected.conditions.length && <button type="button" className="project-inline-button phase-remove"
        onClick={() => update(phases.filter(p => p.id !== selected.id))}>Remove empty phase</button>}
    </div>
  </section>;
}
