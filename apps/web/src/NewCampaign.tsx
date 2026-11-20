import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { label, post, request } from './api';
import { Empty, Icon, Loading, Notice, SectionHeading } from './components';
import type { Backend, CampaignSpec, Catalog, Health, Method } from './types';
import { workerFor } from './workerStatus';
import ReferencePreview from './ReferencePreview';
import { HelpTutorial } from './HelpTutorial';
import { campaignSetupGuide, projectCampaignGuide } from './campaignTutorial';
import { projectCampaignSetup } from './campaignHistory';
import { analysisOptions } from './projectTypes';
import type { Project } from './projectTypes';

export function NewProjectCampaign() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const selected = projects?.find(project => project.id === selectedId);
  useEffect(() => {
    let current = true;
    setError('');
    void request<{ items: Project[] }>('/projects').then(data => {
      if (current) setProjects(data.items);
    }).catch((failure: Error) => { if (current) setError(failure.message); });
    return () => { current = false; };
  }, [attempt]);
  return <>
    <a className="back-link" href="#/campaigns">All campaigns</a>
    <SectionHeading title="New campaign" description="Choose the prototype you want to test across conditions."
      action={Boolean(projects?.length) && <HelpTutorial title="New campaign tutorial" steps={projectCampaignGuide(Boolean(selected))}/>}/>
    {error ? <Notice tone="error">{error} <button className="project-inline-button" onClick={() => setAttempt(value => value + 1)}>Retry</button></Notice>
      : !projects ? <Loading/> : !projects.length ? <section className="card"><Empty icon="layers" title="Create a project to start a campaign"
        action={<a className="button primary" href="#/projects/new">Create project</a>}>A project holds the model, inputs and success criteria for its campaigns.</Empty></section>
      : <section className="card campaign-project-picker"><div className="card-pad">
        <label className="field" data-tour="project-campaign-choice">Project
          <select value={selected?.id ?? ''} onChange={event => setSelectedId(event.target.value)}>
            <option value="">Choose a saved project</option>
            {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
        {selected && <>
          <div className="campaign-project-summary"><p>{selected.goal}</p><span>{analysisOptions.find(item => item.value === selected.analysis_type)?.title ?? label(selected.analysis_type)} · revision {selected.revision}</span></div>
          <div className="analysis-actions"><a className="button primary" data-tour="project-campaign-configure" href={projectCampaignSetup(selected.id)}>Configure campaign<Icon name="chevron" size={16}/></a>
            <a className="text-link" href={'#/projects/' + encodeURIComponent(selected.id) + '?tab=phases'}>Review task phases</a></div>
        </>}
      </div></section>}
  </>;
}

export default function NewBenchmarkCampaign({ catalog, health, onClose, onCreated }: { catalog: Catalog | null; health: Health | null; onClose: () => void; onCreated: (id: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState('Camera & lighting investigation');
  const canUseRobot = Boolean(workerFor(health, 'libero')?.online && health?.readiness.qualified);
  const syntheticOnline = Boolean(workerFor(health, 'synthetic')?.online);
  const [backend, setBackend] = useState<Backend>(canUseRobot && !syntheticOnline ? 'libero' : 'synthetic');
  const [method, setMethod] = useState<Method>('sobol_local_mix');
  const [count, setCount] = useState<CampaignSpec['candidate_count']>(32);
  const [seed, setSeed] = useState(42);
  const [camera, setCamera] = useState(4);
  const [lighting, setLighting] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submission = useRef<{ spec: string; key: string } | null>(null);
  useEffect(() => { const node = dialog.current; node?.showModal(); return () => node?.close(); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    const spec: CampaignSpec = { name: name.trim(), backend, method, candidate_count: count, seed, domain: { main_camera_dx_m: [-camera / 100, camera / 100], light_scale: [1 - lighting / 100, 1 + lighting / 100] }, state_ids: [0, 1], confirmation_state_ids: [2, 3, 4, 5, 6, 7, 8, 9, 10, 11] };
    const serialized = JSON.stringify(spec);
    if (submission.current?.spec !== serialized) submission.current = { spec: serialized, key: crypto.randomUUID() };
    try { const result = await post<{ campaign_id: string }>('/campaigns', spec, submission.current.key); onCreated(result.campaign_id); }
    catch (e) { setError((e as Error).message); setBusy(false); }
  }
  return <dialog ref={dialog} className="campaign-dialog" onCancel={e => { if (e.target === dialog.current) onClose(); }} onClick={e => { if (e.target === dialog.current && !busy) onClose(); }} aria-labelledby="new-campaign-title">
    <div className="dialog-heading">
      <div><h2 id="new-campaign-title">New bowl benchmark</h2><p>Test the bowl-placement task under camera and lighting changes.</p></div>
      <div className="analysis-actions">
        <HelpTutorial title="Campaign tutorial" steps={campaignSetupGuide}/>
        <button type="button" className="icon-button" aria-label="Close benchmark setup" onClick={onClose} disabled={busy}><Icon name="close"/></button>
      </div>
    </div>
    <form onSubmit={submit}>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <label className="field" data-tour="campaign-name">Campaign name<input autoFocus value={name} onChange={e => setName(e.target.value)} required maxLength={100}/></label>
        <fieldset className="backend-options" data-tour="campaign-mode"><legend>Execution mode</legend>
          <label className={`radio-card ${backend === 'synthetic' ? 'chosen' : ''}`}><input type="radio" name="backend" checked={backend === 'synthetic'} onChange={() => setBackend('synthetic')}/><div><strong>Synthetic validation</strong><span>{syntheticOnline ? 'Synthetic worker connected.' : 'Queues until a synthetic worker connects.'}</span></div><span className="mini-tag">CPU</span></label>
          <label className={`radio-card ${backend === 'libero' ? 'chosen' : ''} ${!canUseRobot ? 'disabled' : ''}`}><input type="radio" name="backend" checked={backend === 'libero'} onChange={() => setBackend('libero')} disabled={!canUseRobot}/><div><strong>LIBERO robot experiment</strong><span>{canUseRobot ? 'Qualified robot worker connected.' : 'Requires a qualified LIBERO worker on your execution PC.'}</span></div><span className="mini-tag">GPU</span></label>
        </fieldset>
        <ReferencePreview/>
        {backend === 'synthetic' && <Notice>Synthetic runs validate the software workflow. Their outcomes and traces are generated test data and provide no evidence about robot performance.</Notice>}
        <div className="form-grid"><label className="field" data-tour="campaign-method">Search method<select value={method} onChange={e => setMethod(e.target.value as Method)}><option value="sobol_local_mix">Sobol + local search</option><option value="sobol">Scrambled Sobol</option><option value="random">Uniform random</option></select></label><label className="field" data-tour="campaign-budget">Candidate budget<select value={count} onChange={e => setCount(Number(e.target.value) as CampaignSpec['candidate_count'])}><option value={8}>8 candidates · 16 search episodes</option><option value={16}>16 candidates · 32 search episodes</option><option value={32}>32 candidates · 64 search episodes</option></select></label></div>
        <p className="field-help">{method === 'sobol_local_mix' ? count <= 16 ? 'This budget uses only the Sobol warm-up. Local adaptation starts at candidate 17; choose 32 candidates to exercise it.' : 'Use 16 Sobol warm-up candidates, then mix global proposals with local changes around observed failures.' : method === 'sobol' ? 'Explore the domain with a seeded, scrambled Sobol sequence.' : 'Draw independent seeded samples uniformly across the declared domain.'}</p>
        <div className="domain-fields"><div className="form-section-heading"><h3>Scene-change domain</h3><span>Reference: 0 cm · 1.00×</span></div><label className="range-field" data-tour="campaign-camera"><span>Camera displacement <strong>±{camera.toFixed(1)} cm</strong></span><input type="range" min="0.5" max={Math.min(4, (catalog?.domain.main_camera_dx_m[1] ?? .04) * 100)} step="0.5" value={camera} onChange={e => setCamera(Number(e.target.value))}/><small>Main camera translation; wrist camera pose stays fixed.</small></label><label className="range-field" data-tour="campaign-light"><span>Lighting intensity <strong>{(1 - lighting / 100).toFixed(2)}–{(1 + lighting / 100).toFixed(2)}×</strong></span><input type="range" min="5" max="30" step="5" value={lighting} onChange={e => setLighting(Number(e.target.value))}/><small>Scale scene lighting from its reference values.</small></label></div>
        <label className="field seed-field" data-tour="campaign-seed">Random seed<input type="number" min="0" max="2147483647" step="1" value={seed} onChange={e => setSeed(Number(e.target.value))} required/><span className="field-help">Saved with the campaign for reproducible proposals.</span></label>
        <div className="budget-preview"><Icon name="layers"/><div><strong>{count * 2} search episodes</strong><span>Plus 2 reference checks, up to 32 reduction + 20 confirmation episodes, and 2 shared infrastructure retries.</span></div><b>{count * 2 + 56}<small>attempt ceiling</small></b></div>
      </div>
      <div className="dialog-footer"><button className="button secondary" type="button" onClick={onClose} disabled={busy}>Cancel</button><button className="button primary" type="submit" data-tour="campaign-start" disabled={busy || !name.trim() || (backend === 'libero' && !canUseRobot)}>{busy ? <span className="spinner"/> : <Icon name="play" size={16}/>} {busy ? 'Creating campaign…' : backend === 'synthetic' ? 'Start synthetic validation' : 'Start robot campaign'}</button></div>
    </form>
  </dialog>;
}


