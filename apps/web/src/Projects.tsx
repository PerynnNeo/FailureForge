import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { ApiError, formatTime, label, post, request } from './api';
import { Icon, Loading, Notice, SectionHeading } from './components';
import { analysisOptions, assetKinds, emptyProject, projectInput, stageOptions } from './projectTypes';
import type { AssetKind, Project, ProjectCatalog, ProjectInput, ProjectParameter, ProjectTestPlan } from './projectTypes';
import ProjectAnalysis from './ProjectAnalysis';
import './projects.css';

const go = (path: string) => { window.location.hash = path; };
const message = (error: unknown) => error instanceof Error ? error.message : 'The change could not be saved. Please try again.';
const stageName = (value: string) => stageOptions.find(item => item.value === value)?.short ?? label(value);
const analysisName = (value: string) => analysisOptions.find(item => item.value === value)?.title ?? label(value);
const bytes = (value: number) => value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`;
const numeric = (value: string) => value === '' ? null : Number(value);
const decodeSegment = (value: string) => { try { return decodeURIComponent(value); } catch { return value; } };

export default function Projects({ route, notify }: { route: string; notify: (value: string) => void }) {
  const [catalog, setCatalog] = useState<ProjectCatalog | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const loadCatalog = useCallback(async () => { try { setCatalog(await request<ProjectCatalog>('/projects/catalog')); setCatalogError(''); } catch (error) { setCatalogError(message(error)); } }, []);
  useEffect(() => { void loadCatalog(); }, [loadCatalog]);
  const id = route.startsWith('/projects/') ? decodeSegment(route.split('/')[2]) : undefined;
  return <div className="projects-workspace">
    {catalogError && <Notice tone="warning">Project guidance could not load. {catalogError} <button className="project-inline-button" onClick={() => void loadCatalog()}>Retry</button></Notice>}
    {id === 'new' ? <ProjectCreate catalog={catalog} notify={notify}/> : id ? <ProjectDetail key={id} id={id} catalog={catalog} notify={notify}/> : <ProjectList/>}
  </div>;
}

function ProjectList() {
  const [items, setItems] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const load = useCallback(async () => { setLoading(true); try { setItems((await request<{ items: Project[] }>('/projects')).items); setError(''); } catch (error) { setError(message(error)); } finally { setLoading(false); } }, []);
  useEffect(() => { void load(); }, [load]);
  const filtered = items.filter(item => `${item.name} ${item.goal} ${analysisName(item.analysis_type)}`.toLowerCase().includes(query.toLowerCase()));
  return <>
    <SectionHeading eyebrow="FROM IDEA TO EVIDENCE" title="Your projects" description="Bring what you have. Build the information a meaningful test needs." action={<a href="#/projects/new" className="button primary"><Icon name="plus" size={18}/>New project</a>}/>
    <section className="project-intro"><div><span className="eyebrow">START AT YOUR STAGE</span><h3>A place for the design,<br/>the assumptions, and the test.</h3><p>Start with a concept, CAD design, robot model, existing simulation, or physical prototype. Keep requirements, files, and test plans together as your project develops.</p></div><div className="project-stage-map" aria-label="Supported entry stages">{stageOptions.map((stage, index) => <span key={stage.value}><b>{String(index + 1).padStart(2, '0')}</b>{stage.short}</span>)}</div></section>
    <div className="project-capability-note"><Icon name="info" size={19}/><p><strong>Project analyses</strong> use explicit model inputs for motion, calibration, structural, and thermal studies. Open a project’s Analysis tab to run a study. The robot policy benchmark is in <a href="#/campaigns">Campaigns</a>.</p></div>
    {error && <Notice tone="error">{error} <button className="project-inline-button" onClick={() => void load()}>Try again</button></Notice>}
    {loading ? <Loading/> : items.length ? <>
      <div className="project-list-toolbar"><label className="search-input"><Icon name="search" size={19}/><input aria-label="Search projects" placeholder="Search your projects" value={query} onChange={event => setQuery(event.target.value)}/></label><span>{filtered.length} {filtered.length === 1 ? 'project' : 'projects'}</span></div>
      <div className="project-list">{filtered.map(item => <a className="project-list-card" href={`#/projects/${encodeURIComponent(item.id)}`} key={item.id}><div className="project-list-card-top"><span className="project-type"><Icon name={item.analysis_type === 'robot_behavior' ? 'runtime' : item.analysis_type === 'structural' ? 'layers' : 'sliders'} size={20}/>{analysisName(item.analysis_type)}</span><Icon name="chevron" size={19}/></div><h3>{item.name}</h3><p>{item.goal}</p><div className="project-card-meta"><span>{stageName(item.entry_stage)}</span><span>{item.assets.length} files</span><span>{item.test_plans.length} test plans</span></div><div className="project-card-bottom"><span>Next: {label(item.readiness.phase)}</span><small>Updated {formatTime(item.updated_at)}</small></div></a>)}</div>
      {!filtered.length && <div className="project-empty"><h3>No matching projects</h3><p>Try a different name, task, or analysis.</p></div>}
    </> : !error && <div className="project-empty"><div className="project-empty-icon"><Icon name="layers" size={30}/></div><h3>Start with a question worth testing.</h3><p>You do not need a finished robot or a simulation model to create a project. Your first step is to describe what the design should do.</p><a href="#/projects/new" className="button primary"><Icon name="plus" size={17}/>Create your first project</a></div>}
  </>;
}

function Field({ label: title, value, onChange, multiline = false, hint, required = false, placeholder, maxLength = 3000 }: { label: string; value: string; onChange: (value: string) => void; multiline?: boolean; hint?: string; required?: boolean; placeholder?: string; maxLength?: number }) {
  return <label className="project-field"><span>{title}{required && <b aria-hidden="true"> *</b>}</span>{multiline ? <textarea value={value} onChange={event => onChange(event.target.value)} required={required} placeholder={placeholder} rows={3} maxLength={maxLength}/> : <input type="text" value={value} onChange={event => onChange(event.target.value)} required={required} placeholder={placeholder} maxLength={maxLength}/>} {hint && <small>{hint}</small>}</label>;
}

function SourceFields({ draft, update, catalog }: { draft: ProjectInput; update: (patch: Partial<ProjectInput>) => void; catalog: ProjectCatalog | null }) {
  return <div className="project-form-grid"><label className="project-field"><span>Robot / hardware source</span><select value={draft.robot_source} onChange={event => update({ robot_source: event.target.value as ProjectInput['robot_source'], robot_template: null })}><option value="custom">My own design or existing project</option><option value="supported" disabled={!catalog?.robot_templates.length}>Choose a catalog robot</option></select><small>The reference two-finger hand supports motion studies. The other catalog entries provide preparation guidance.</small></label>{draft.robot_source === 'supported' && <label className="project-field"><span>Catalog robot</span><select required value={draft.robot_template ?? ''} onChange={event => update({ robot_template: event.target.value || null })}><option value="">Choose a template</option>{catalog?.robot_templates.map(item => <option key={item.id} value={item.id}>{item.label} · {item.execution_available ? 'Executable reference' : 'Preparation reference'}</option>)}</select><small>{catalog?.robot_templates.find(item => item.id === draft.robot_template)?.description ?? 'Select a reference robot to organize your integration.'}</small></label>}</div>;
}

function ProjectCreate({ catalog, notify }: { catalog: ProjectCatalog | null; notify: (value: string) => void }) {
  const [draft, setDraft] = useState<ProjectInput>(emptyProject);
  const [step, setStep] = useState(0);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const update = (patch: Partial<ProjectInput>) => setDraft(value => ({ ...value, ...patch }));
  const next = (value: number) => { setStep(value); setError(''); requestAnimationFrame(() => titleRef.current?.focus()); };
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (step < 2) { next(step + 1); return; }
    setSaving(true); setError('');
    try { const result = await post<Project>('/projects', draft); notify('Project created. Review the preparation checklist and add your evidence.'); go(`/projects/${encodeURIComponent(result.id)}`); } catch (error) { setError(message(error)); } finally { setSaving(false); }
  }
  return <><a className="back-link" href="#/projects">All projects</a><SectionHeading eyebrow="NEW PROJECT" title="Start with what you have." description="A working brief is enough to begin. Add detail as the design develops."/>
    <ol className="project-wizard-progress" aria-label="Project setup steps">{['Starting point', 'Analysis', 'Project brief'].map((title, index) => <li key={title} className={step === index ? 'current' : index < step ? 'complete' : ''} aria-current={step === index ? 'step' : undefined}><span>{index < step ? <Icon name="check" size={15}/> : index + 1}</span>{title}</li>)}</ol>
    <form className="project-wizard" onSubmit={event => void submit(event)}><fieldset disabled={saving}>
      <header><span className="eyebrow">STEP {step + 1} OF 3</span><h3 ref={titleRef} tabIndex={-1}>{['Where are you starting?', 'What do you want to understand?', 'Describe the job and the question.'][step]}</h3><p>{['Choose your current stage. You can update it as your project develops.', 'The analysis determines the information and solver your experiment will need.', 'Write an initial hypothesis and acceptance rule. You can revise both later.'][step]}</p></header>
      {step === 0 && <div className="project-choice-list">{stageOptions.map(item => <label key={item.value} className={`project-choice ${draft.entry_stage === item.value ? 'selected' : ''}`}><input type="radio" name="stage" checked={draft.entry_stage === item.value} value={item.value} onChange={() => update({ entry_stage: item.value })}/><div><strong>{item.title}</strong><span>{item.description}</span></div></label>)}</div>}
      {step === 1 && <><div className="project-choice-list">{analysisOptions.map(item => <label key={item.value} className={`project-choice ${draft.analysis_type === item.value ? 'selected' : ''}`}><input type="radio" name="analysis" checked={draft.analysis_type === item.value} value={item.value} onChange={() => update({ analysis_type: item.value })}/><div><strong>{item.title}</strong><span>{item.description}</span></div></label>)}</div><Notice>{analysisOptions.find(item => item.value === draft.analysis_type)?.boundary}</Notice></>}
      {step === 2 && <div className="project-form-stack"><div className="project-brief-context"><span>{stageName(draft.entry_stage)}</span><span>{analysisName(draft.analysis_type)}</span></div><Field label="Project name" required maxLength={120} value={draft.name} onChange={name => update({ name })} placeholder="For example: Hand grip reliability"/><Field label="What should the design do?" multiline required value={draft.goal} onChange={goal => update({ goal })} placeholder={draft.analysis_type === 'robot_behavior' ? 'Rotate a small object in the hand without dropping it.' : draft.analysis_type === 'structural' ? 'Support the specified payload without permanent deformation.' : 'Keep the motor below its temperature limit during repeated operation.'}/><Field label="Initial success criteria" multiline required value={draft.success_criteria} onChange={success_criteria => update({ success_criteria })} hint="Describe a measurable result where possible. Record any unconfirmed thresholds as assumptions." placeholder={draft.analysis_type === 'robot_behavior' ? 'Rotate at least 90 degrees within 5 seconds, with no drop.' : 'Describe the limit, operating condition, and duration.'}/><SourceFields draft={draft} update={update} catalog={catalog}/></div>}
      {error && <Notice tone="error">{error}</Notice>}
      <footer>{step > 0 ? <button type="button" className="button secondary" onClick={() => next(step - 1)}>Back</button> : <a className="button secondary" href="#/projects">Cancel</a>}<span>{step === 2 ? 'Creates a planning project. No experiment will run.' : 'No model or upload required to begin.'}</span><button type="submit" className="button primary">{saving ? 'Creating project…' : step === 2 ? 'Create project' : 'Continue'}</button></footer>
    </fieldset></form>
  </>;
}

type DetailTab = 'overview' | 'files' | 'parameters' | 'tests' | 'analysis';
function ProjectDetail({ id, catalog, notify }: { id: string; catalog: ProjectCatalog | null; notify: (value: string) => void }) {
  const [project, setProject] = useState<Project | null>(null);
  const [draft, setDraft] = useState<ProjectInput | null>(null);
  const [tab, setTab] = useState<DetailTab>('overview');
  const [analysisOpened, setAnalysisOpened] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<AssetKind>('requirements');
  const inputRef = useRef<HTMLInputElement>(null);
  const acceptSaved = (result: Project) => { setProject(result); setDraft(projectInput(result)); setConflict(false); setError(''); };
  const load = useCallback(async () => { try { acceptSaved(await request<Project>(`/projects/${encodeURIComponent(id)}`)); } catch (error) { setError(message(error)); } }, [id]);
  useEffect(() => { void load(); }, [load]);
  const dirty = !!project && !!draft && JSON.stringify(projectInput(project)) !== JSON.stringify(draft);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    const beforeRouteChange = (event: Event) => { if (!window.confirm('You have unsaved project changes. Leave this project and discard the draft?')) event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    window.addEventListener('failureforge:before-route-change', beforeRouteChange);
    return () => { window.removeEventListener('beforeunload', warn); window.removeEventListener('failureforge:before-route-change', beforeRouteChange); };
  }, [dirty]);
  const update = (patch: Partial<ProjectInput>) => setDraft(value => value ? { ...value, ...patch } : null);
  async function save(event: FormEvent) {
    event.preventDefault(); if (!project || !draft) return;
    setSaving(true); setError('');
    try { acceptSaved(await post<Project>(`/projects/${encodeURIComponent(id)}`, { ...draft, expected_revision: project.revision })); notify('Project saved. The preparation checklist has been recalculated.'); } catch (error) { setError(message(error)); setConflict(error instanceof ApiError && error.status === 409); } finally { setSaving(false); }
  }
  async function upload() {
    if (!file || !project || dirty || saving) return;
    if (file.size > (catalog?.limits.asset_bytes ?? 10485760)) { setError(`The file is too large. The current limit is ${bytes(catalog?.limits.asset_bytes ?? 10485760)} per file.`); return; }
    setSaving(true); setError('');
    try {
      const result = await request<Project>(`/projects/${encodeURIComponent(id)}/assets?filename=${encodeURIComponent(file.name)}&kind=${kind}`, { method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' } });
      acceptSaved(result); setFile(null); if (inputRef.current) inputRef.current.value = ''; notify('File stored. Review the inspection notes before using it in a test.');
    } catch (error) { setError(message(error)); } finally { setSaving(false); }
  }
  if (!project || !draft) return error ? <><a className="back-link" href="#/projects">All projects</a><Notice tone="error">{error} <button className="project-inline-button" onClick={() => void load()}>Retry</button></Notice></> : <Loading/>;
  const analysis = analysisOptions.find(item => item.value === draft.analysis_type)!;
  return <>
    <a className="back-link" href="#/projects">All projects</a>
    <SectionHeading eyebrow="PROJECT WORKSPACE" title={project.name} description={`${analysisName(project.analysis_type)} · ${stageName(project.entry_stage)} · Revision ${project.revision}`} action={<a className="button secondary" href={`/api/projects/${encodeURIComponent(project.id)}/export`} download><Icon name="download" size={17}/>Export saved report</a>}/>
    <div className="project-capability-note"><Icon name="info" size={19}/><p>{analysis.boundary}</p></div>
    <Journey readiness={project.readiness}/>
    <div className="project-detail-layout">
      <div className="project-detail-main">
        <nav className="project-tabs" aria-label="Project sections">{([['overview', 'Overview'], ['files', `Files (${project.assets.length})`], ['parameters', `Parameters (${draft.parameters.length})`], ['tests', `Test plans (${draft.test_plans.length})`], ['analysis', 'Analysis & runs']] as [DetailTab, string][]).map(([key, title]) => <button key={key} type="button" className={tab === key ? 'active' : ''} aria-current={tab === key ? 'page' : undefined} onClick={() => { if (key === 'analysis') setAnalysisOpened(true); setTab(key); }}>{title}</button>)}</nav>
        {error && <Notice tone="error">{error}{conflict && <div className="project-conflict"><p>Another change was saved while you were editing. Your draft is still here. Copy anything you need before reloading the saved version.</p><button className="button secondary" type="button" onClick={() => void load()}>Discard draft and reload saved version</button></div>}</Notice>}
        {analysisOpened && <div hidden={tab !== 'analysis'}><ProjectAnalysis key={project.analysis_type} project={project} dirty={dirty} reload={load} notify={notify}/></div>}
        <form hidden={tab === 'analysis' && !dirty} onSubmit={event => void save(event)}><fieldset className="project-edit-fieldset" disabled={saving}>
          {tab === 'overview' && <section className="project-panel"><PanelHeader title="The working brief" description="Keep the question specific. Update the starting stage as your design develops."/><div className="project-form-stack"><Field label="Project name" value={draft.name} onChange={name => update({ name })} required maxLength={120}/><div className="project-form-grid"><label className="project-field"><span>Current entry stage</span><select value={draft.entry_stage} onChange={event => update({ entry_stage: event.target.value as ProjectInput['entry_stage'] })}>{stageOptions.map(item => <option value={item.value} key={item.value}>{item.short}</option>)}</select></label><label className="project-field"><span>Analysis</span><select value={draft.analysis_type} onChange={event => update({ analysis_type: event.target.value as ProjectInput['analysis_type'] })}>{analysisOptions.map(item => <option value={item.value} key={item.value}>{item.title}</option>)}</select></label></div><Field label="What should the design do?" value={draft.goal} onChange={goal => update({ goal })} required multiline/><Field label="Success criteria" value={draft.success_criteria} onChange={success_criteria => update({ success_criteria })} required multiline hint="Define measurable acceptance rules. These are test requirements, not measured outcomes."/><SourceFields draft={draft} update={update} catalog={catalog}/><Field label="Design notes and open questions" maxLength={6000} value={draft.notes} onChange={notes => update({ notes })} multiline placeholder="What remains unknown? Which assumptions should be checked first?"/></div></section>}
          {tab === 'files' && <section className="project-panel"><PanelHeader title="The files behind the design" description="Store source files and inspect their preparation notes. Uploading a file does not convert it, qualify its physics, or run its code."/><div className="project-upload"><div className="project-form-grid"><label className="project-field"><span>File purpose</span><select value={kind} onChange={event => setKind(event.target.value as AssetKind)}>{assetKinds.map(item => <option value={item.value} key={item.value}>{item.title}</option>)}</select><small>{assetKinds.find(item => item.value === kind)?.hint}</small></label><label className="project-field"><span>Choose a file</span><input ref={inputRef} type="file" accept={catalog?.allowed_extensions[kind]?.join(',')} onChange={event => setFile(event.target.files?.[0] ?? null)}/><small>Up to {bytes(catalog?.limits.asset_bytes ?? 10485760)} per file. Files stay in this local workspace. {catalog?.allowed_extensions[kind]?.join(', ')}</small></label></div><div className="project-upload-footer"><span>{dirty ? 'Save your draft before adding a file.' : file ? `${file.name} · ${bytes(file.size)}` : 'Source files are stored as supplied.'}</span><button type="button" className="button primary" disabled={!file || dirty || project.assets.length >= (catalog?.limits.max_assets ?? 40)} onClick={() => void upload()}><Icon name="plus" size={17}/>{saving ? 'Uploading…' : 'Upload file'}</button></div></div><div className="project-assets">{project.assets.length ? project.assets.map(asset => <article className="project-asset" key={asset.id}><div className="project-asset-heading"><Icon name="file" size={22}/><div><h4>{asset.filename}</h4><span>{assetKinds.find(item => item.value === asset.kind)?.title ?? label(asset.kind)} · {bytes(asset.size_bytes)}</span></div><a href={asset.download_url} className="icon-button" download aria-label={`Download ${asset.filename}`}><Icon name="download" size={18}/></a></div><p>{asset.inspection.summary}</p>{asset.inspection.warnings.length > 0 && <ul className="project-inspection-warnings">{asset.inspection.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}<details><summary>File identity and inspection details</summary><dl><dt>SHA-256</dt><dd className="mono">{asset.sha256}</dd><dt>Stored</dt><dd>{formatTime(asset.created_at)}</dd><dt>Inspection</dt><dd>{label(asset.inspection.status)} · {asset.inspection.format}</dd></dl>{Object.keys(asset.inspection.details).length > 0 && <pre>{JSON.stringify(asset.inspection.details, null, 2)}</pre>}</details></article>) : <div className="project-inline-empty"><Icon name="file" size={26}/><h4>No source files yet</h4><p>A concept can begin without files. Add the evidence that supports your next preparation step.</p></div>}</div></section>}
          {tab === 'overview' && <RevisionHistory project={project}/>}
          {tab === 'parameters' && <Parameters draft={draft} update={update} limit={catalog?.limits.max_parameters ?? 80}/>}
          {tab === 'tests' && <TestPlans draft={draft} update={update} limit={catalog?.limits.max_test_plans ?? 30}/>}
          <div className={`project-savebar ${dirty ? 'has-changes' : ''}`}><div><strong>{saving ? 'Saving your work…' : dirty ? 'You have unsaved changes' : `Saved · Revision ${project.revision}`}</strong><span>{dirty ? 'Save to update readiness. Export includes the saved version.' : `Last updated ${formatTime(project.updated_at)}`}</span></div><button type="submit" className="button primary" disabled={!dirty}>{saving ? 'Saving…' : 'Save changes'}</button></div>
        </fieldset></form>
      </div>
      <aside className="project-readiness"><div className="project-readiness-heading"><Icon name="check" size={20}/><h3>Preparation checklist</h3></div><p className="project-readiness-intro">Based on saved information. A complete checklist is not simulator qualification.</p>{dirty && <div className="project-draft-note">Save your draft to refresh these checks.</div>}<ul>{project.readiness.checks.map(check => <li key={check.id}><span className={`project-check-icon ${check.status}`}><Icon name={check.status === 'complete' ? 'check' : check.status === 'blocked' ? 'stop' : check.status === 'review' ? 'info' : 'plus'} size={14}/></span><div><strong>{check.label}</strong><span className={`project-check-status ${check.status}`}>{label(check.status)}</span><p>{check.detail}</p></div></li>)}</ul><div className="project-next-action"><span className="eyebrow">NEXT ACTION</span><p>{project.readiness.next_action}</p></div>{project.readiness.limitations.length > 0 && <details className="project-limitations"><summary>Scope and limitations</summary><ul>{project.readiness.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}</aside>
    </div>
  </>;
}

function PanelHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <header className="project-panel-header"><div><h3>{title}</h3><p>{description}</p></div>{action}</header>;
}

function RevisionHistory({ project }: { project: Project }) {
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<Array<{ revision: number; saved_at: string; reason: string }>>([]);
  const [error, setError] = useState('');
  const path = `/projects/${encodeURIComponent(project.id)}/revisions`;
  useEffect(() => {
    let current = true;
    if (open) void request<{items: typeof history}>(path)
      .then(data => { if (current) { setHistory(data.items); setError(''); } })
      .catch((failure: Error) => { if (current) setError(failure.message); });
    return () => { current = false; };
  }, [open, path, project.revision]);
  return <details className="project-revisions" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Saved project revisions</summary>
    {error ? <Notice tone="error">{error}</Notice> : history.length ? <ul>{history.map(item => <li key={item.revision}>
      <span>Revision {item.revision} · {label(item.reason)} · {formatTime(item.saved_at)}</span>
      <a className="text-link" href={`/api${path}/${item.revision}`} download={`${project.id}-revision-${item.revision}.json`}>Export snapshot</a>
    </li>)}</ul> : <p className="small muted">Loading revisions…</p>}
  </details>;
}

function Journey({ readiness }: { readiness: Project['readiness'] }) {
  return <section className="project-journey" aria-label="Project journey"><div className="project-journey-label"><span className="eyebrow">PROJECT JOURNEY</span><span>Preparation stages reflect the saved project inputs. See Analysis & runs for recorded results.</span></div><ol>{readiness.phases.map((phase, index) => <li key={phase.id} className={phase.status} aria-current={phase.status === 'current' ? 'step' : undefined}><span className="project-phase-number">{phase.status === 'complete' ? <Icon name="check" size={15}/> : String(index + 1).padStart(2, '0')}</span><div><strong>{phase.label}</strong><small>{label(phase.status)}</small><details className="project-phase-detail"><summary aria-label={`About the ${phase.label.toLowerCase()} phase`}>What happens here</summary><p>{phase.detail}</p></details></div></li>)}</ol></section>;
}

function Parameters({ draft, update, limit }: { draft: ProjectInput; update: (patch: Partial<ProjectInput>) => void; limit: number }) {
  const edit = (index: number, patch: Partial<ProjectParameter>) => update({ parameters: draft.parameters.map((item, current) => current === index ? { ...item, ...patch } : item) });
  const add = () => update({ parameters: [...draft.parameters, { name: '', value: '', unit: '', source: 'estimated', evidence: '', range_min: null, range_max: null }] });
  const guide = draft.analysis_type === 'robot_behavior' ? 'Examples: link mass, joint limits, motor torque, command delay, contact friction. A material label alone does not establish these values.' : draft.analysis_type === 'structural' ? 'Examples: elastic modulus, Poisson ratio, yield strength, applied load, support conditions. Properties must match the actual material and analysis assumptions.' : 'Examples: thermal conductivity, heat input, ambient temperature, and convection assumptions. State operating conditions and units.';
  return <section className="project-panel"><PanelHeader title="What the model assumes" description="Record values, where they came from, and what remains uncertain." action={<button type="button" className="button secondary" disabled={draft.parameters.length >= limit} onClick={add}><Icon name="plus" size={16}/>Add parameter</button>}/><div className="project-context-help"><Icon name="info" size={18}/><p>{guide}</p></div>
    <div className="project-editor-list">{draft.parameters.length ? draft.parameters.map((parameter, index) => <section className="project-editor" key={index} aria-label={`Parameter ${index + 1}`}><div className="project-editor-heading"><span>PARAMETER {String(index + 1).padStart(2, '0')}</span><button type="button" className="project-inline-button" onClick={() => update({ parameters: draft.parameters.filter((_, current) => current !== index) })}>Remove<span className="sr-only"> parameter {index + 1}</span></button></div><div className="project-form-stack"><Field label="Parameter name" value={parameter.name} required onChange={name => edit(index, { name })} placeholder="For example: fingertip friction" maxLength={100}/><div className="project-form-grid"><Field label="Value or assumption" maxLength={300} value={parameter.value} required onChange={value => edit(index, { value })} placeholder="A numeric value or explicit description"/><Field label="Unit" value={parameter.unit} onChange={unit => edit(index, { unit })} placeholder="kg, N·m, °C, or dimensionless" maxLength={50}/></div><div className="project-form-grid"><label className="project-field"><span>Where did the value come from?</span><select value={parameter.source} onChange={event => edit(index, { source: event.target.value as ProjectParameter['source'] })}><option value="estimated">Estimated — an assumption to check</option><option value="imported">Imported — copied from a model or file</option><option value="supplier">Supplier — specification or datasheet</option><option value="measured">Measured — observed on hardware</option><option value="calibrated">Calibrated — fitted against measurements</option></select></label><Field label="Evidence / reference" maxLength={1000} value={parameter.evidence} onChange={evidence => edit(index, { evidence })} placeholder="Filename, datasheet, measurement method, or uncertainty" hint="A source label is a declaration. Attach supporting evidence in Files."/></div><div className="project-parameter-range"><div><strong>Exploration range</strong><p>Optional numeric bounds, in the unit above. This records a proposed variation; it does not schedule a test.</p></div><label className="project-field"><span>Minimum</span><input type="number" step="any" value={parameter.range_min ?? ''} required={parameter.range_max != null} onChange={event => edit(index, { range_min: numeric(event.target.value) })}/></label><label className="project-field"><span>Maximum</span><input type="number" step="any" min={parameter.range_min ?? undefined} value={parameter.range_max ?? ''} required={parameter.range_min != null} onChange={event => edit(index, { range_max: numeric(event.target.value) })}/></label></div>{parameter.source === 'estimated' && <div className="project-estimate-note">Results from this assumption would need sensitivity testing or measurement before they could support a hardware conclusion.</div>}</div></section>) : <div className="project-inline-empty"><Icon name="sliders" size={27}/><h4>Make the assumptions visible.</h4><p>Add the properties your intended test depends on. There are no prefilled material or motor values.</p><button type="button" className="button secondary" onClick={add}>Add the first parameter</button></div>}</div>
  </section>;
}

function TestPlans({ draft, update, limit }: { draft: ProjectInput; update: (patch: Partial<ProjectInput>) => void; limit: number }) {
  const edit = (index: number, patch: Partial<ProjectTestPlan>) => update({ test_plans: draft.test_plans.map((item, current) => current === index ? { ...item, ...patch } : item) });
  const add = () => update({ test_plans: [...draft.test_plans, { name: '', objective: '', success_criteria: '', variation: '', timeout_seconds: null }] });
  return <section className="project-panel"><PanelHeader title="A repeatable question for every test" description="Use one project for several scenarios. Each plan has its own objective, pass condition, and allowed changes." action={<button type="button" className="button secondary" disabled={draft.test_plans.length >= limit} onClick={add}><Icon name="plus" size={16}/>Add test plan</button>}/><div className="project-context-help"><Icon name="info" size={18}/><p>Test plans are saved specifications. Executable tasks, solver integration, reference checks, and runtime qualification are still required before custom tests can run.</p></div>
    <div className="project-editor-list">{draft.test_plans.length ? draft.test_plans.map((plan, index) => <section className="project-editor" key={index} aria-label={`Test plan ${index + 1}`}><div className="project-editor-heading"><span>TEST PLAN {String(index + 1).padStart(2, '0')}</span><button type="button" className="project-inline-button" onClick={() => update({ test_plans: draft.test_plans.filter((_, current) => current !== index) })}>Remove<span className="sr-only"> test plan {index + 1}</span></button></div><div className="project-form-stack"><Field label="Test name" required maxLength={120} value={plan.name} onChange={name => edit(index, { name })} placeholder="For example: Rotate an off-center object"/><Field label="Objective and starting conditions" required multiline maxLength={1500} value={plan.objective} onChange={objective => edit(index, { objective })} placeholder="State the starting setup, commanded behavior, and question."/><Field label="Success criteria" required multiline maxLength={1500} value={plan.success_criteria} onChange={success_criteria => edit(index, { success_criteria })} placeholder="Specify the measurements and thresholds for passing."/><Field label="Allowed variations" required multiline maxLength={1500} value={plan.variation} onChange={variation => edit(index, { variation })} placeholder="For example: vary initial object offset from −6 to +6 mm, holding the controller fixed."/><label className="project-field project-timeout"><span>Time limit (seconds, optional)</span><input type="number" min="0.001" max="86400" step="any" value={plan.timeout_seconds ?? ''} onChange={event => edit(index, { timeout_seconds: numeric(event.target.value) })}/><small>The experiment duration or termination limit to implement in the future test adapter.</small></label></div></section>) : <div className="project-inline-empty"><Icon name="campaign" size={28}/><h4>Give each test a clear purpose.</h4><p>Describe the baseline, the allowed changes, and the result that would count as success. Add more plans as your design develops.</p><button type="button" className="button secondary" onClick={add}>Add the first test plan</button></div>}</div>
  </section>;
}
