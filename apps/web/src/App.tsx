import { useCallback, useEffect, useState } from 'react';
import { formatTime, label, methodName, post, request, shortId } from './api';
import { BackendBadge, Empty, Icon, Loading, Notice, SectionHeading, Status } from './components';
import { ScatterPlot } from './Charts';
import { candidateFailureCount } from './candidateOutcomes';
import NewBenchmarkCampaign, { NewProjectCampaign } from './NewCampaign';
import { CampaignList, CampaignTable, NewCampaignLink, useProjectBatches } from './CampaignWorkspace';
import { activeCampaignStatus, campaignHistory } from './campaignHistory';
import type { CampaignRow, ProjectBatch } from './campaignHistory';
import CaseInspector from './CaseInspector';
import CampaignEvidence from './CampaignEvidence';
import { HelpTutorial } from './HelpTutorial';
import { campaignDetailGuide } from './campaignTutorial';
import Projects from './Projects';
import type { Campaign, Catalog, Health } from './types';
import { workerFor, workerLabel } from './workerStatus';
import './styles.css';

const defaultDomain = { main_camera_dx_m: [-.04, .04] as [number, number], light_scale: [.7, 1.3] as [number, number] };
const navigate = (path: string) => { window.location.hash = path; };
const decodeSegment = (value: string) => { try { return decodeURIComponent(value); } catch { return value; } };


export default function App({ route }: { route: string }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [benchmarkOpen, setBenchmarkOpen] = useState(false);
  const [benchmarkError, setBenchmarkError] = useState('');
  const [benchmarksLoaded, setBenchmarksLoaded] = useState(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [toast, setToast] = useState('');
  const refresh = useCallback(async () => {
    const [h, c, list] = await Promise.allSettled([request<Health>('/health'), request<Catalog>('/catalog'), request<{ items: Campaign[] }>('/campaigns')]);
    setConnected(h.status === 'fulfilled');
    if (h.status === 'fulfilled') setHealth(h.value);
    if (c.status === 'fulfilled') setCatalog(c.value);
    if (list.status === 'fulfilled') { setCampaigns(list.value.items); setBenchmarksLoaded(true); setBenchmarkError(''); }
    else setBenchmarkError(`Bowl benchmarks could not load. ${list.reason instanceof Error ? list.reason.message : ''}`);
  }, []);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 4000); return () => clearInterval(timer); }, [refresh]);
  useEffect(() => { setMobileMenu(false); }, [route]);
  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(''), 6500); return () => clearTimeout(timer); }, [toast]);
  const section = route.startsWith('/projects') ? 'projects' : route.startsWith('/campaign') || route.startsWith('/case') ? 'campaigns' : route === '/runtime' ? 'runtime' : 'overview';
  const campaignId = route.startsWith('/campaigns/') ? decodeSegment(route.split('/')[2]) : null;
  const caseId = route.startsWith('/cases/') ? decodeSegment(route.split('/')[2]) : null;
  const projectQuery = section === 'projects' ? new URLSearchParams(route.split('?')[1]) : null;
  const setupBatch = projectQuery?.get('setup') === 'campaign';
  const savedBatch = Boolean(projectQuery?.get('batch'));
  const navSection = setupBatch || savedBatch ? 'campaigns' : section;
  const batches = useProjectBatches(section === 'overview' || (section === 'campaigns' && !campaignId && !caseId));
  const history = campaignHistory(batches.items ?? [], campaigns);
  const historyLoading = (!batches.items && !batches.error) || (!benchmarksLoaded && !benchmarkError);
  const historyError = [batches.error && `Project campaigns could not load. ${batches.error}`, benchmarkError].filter(Boolean).join(' ');
  const retryHistory = () => { batches.retry(); void refresh(); };
  return <div className="app-shell">
    {mobileMenu && <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setMobileMenu(false)}/>}
    <aside className={`sidebar ${mobileMenu ? 'open' : ''}`}>
      <a className="brand" href="#/" aria-label="FailureForge home"><span className="brand-mark"><span/><span/><span/></span><span>Failure<span className="brand-light">Forge</span><small>ROBOTICS INVESTIGATION</small></span></a>
      <div className="workspace-label">WORKSPACE <span>LOCAL</span></div>
      <nav aria-label="Main navigation">
        <a className={navSection === 'overview' ? 'active' : ''} href="#/workspace" aria-current={navSection === 'overview' ? 'page' : undefined}><Icon name="overview"/>Overview</a>
        <a className={navSection === 'projects' ? 'active' : ''} href="#/projects" aria-current={navSection === 'projects' ? 'page' : undefined}><Icon name="layers"/>Projects</a>
        <a className={navSection === 'campaigns' ? 'active' : ''} href="#/campaigns" aria-current={navSection === 'campaigns' ? 'page' : undefined}><Icon name="campaign"/>Campaigns{batches.items && benchmarksLoaded && !historyError && <span className="nav-count">{history.length}</span>}</a>
        <a className={navSection === 'runtime' ? 'active' : ''} href="#/runtime" aria-current={navSection === 'runtime' ? 'page' : undefined}><Icon name="runtime"/>Runtime & setup</a>
      </nav>
      <div className="sidebar-context"><span className="eyebrow">FROM DESIGN TO EVIDENCE</span><strong>Start at your stage.<br/>Prepare a meaningful test.</strong><p>Projects hold your prototype and models.<br/>Campaigns test them across conditions.</p><div className="sidebar-coordinate"><span>PLAN</span><i/><span>TEST</span></div></div>
      <div className="sidebar-bottom"><div className={`connection-dot ${connected && health?.worker.online ? 'online' : ''}`}/><div><strong>{connected === null ? 'Connecting to service' : !connected ? 'API disconnected' : workerLabel(health)}</strong><span>{connected ? 'Local execution workspace' : 'Start your local API to connect'}</span></div></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileMenu(true)}><Icon name="menu"/></button><span>Workspace</span><Icon name="chevron" size={13}/><strong>{setupBatch ? 'Campaign setup' : savedBatch ? 'Campaign results' : section === 'projects' ? route === '/projects/new' ? 'New project' : route.startsWith('/projects/') ? 'Project detail' : 'Projects' : section === 'overview' ? 'Overview' : section === 'runtime' ? 'Runtime & setup' : caseId ? 'Case investigation' : campaignId === 'new' ? 'New campaign' : campaignId ? 'Bowl benchmark' : 'Campaigns'}</strong></div><div className="topbar-right"><span className="development-label">DEVELOPMENT WORKSPACE</span><div className="avatar" aria-label="Local workspace">FF</div></div></header>
      <main id="main-content">
        {connected === false && <div className="connection-banner" role="status"><Icon name="info" size={18}/><span>API disconnected. Saved investigations will appear when the local service is running.</span><button onClick={() => void refresh()}>Retry connection</button></div>}
        {section === 'projects' ? <Projects route={route} notify={setToast}/> : caseId ? <CaseInspector key={caseId} id={caseId} notify={setToast}/> : campaignId === 'new' ? <NewProjectCampaign/> : campaignId ? <CampaignDetail key={campaignId} id={campaignId} notify={setToast}/> : section === 'runtime' ? <Runtime health={connected ? health : null} catalog={catalog} connected={connected} refresh={refresh}/> : section === 'campaigns' ? <CampaignList rows={history} loading={historyLoading} error={historyError} retry={retryHistory} benchmarkOpen={benchmarkOpen} onBenchmark={() => setBenchmarkOpen(true)}/> : <Overview rows={history} batches={batches.items} benchmarks={campaigns} benchmarksLoaded={benchmarksLoaded} loading={historyLoading} error={historyError} retry={retryHistory}/>}
      </main>
      <footer className="page-footer"><span>FailureForge <b>·</b> Controlled changes. Reproducible evidence.</span><span>Local-first research workspace</span></footer>
    </div>
    {benchmarkOpen && <NewBenchmarkCampaign catalog={catalog} health={connected ? health : null} onClose={() => setBenchmarkOpen(false)} onCreated={id => { setBenchmarkOpen(false); navigate(`/campaigns/${encodeURIComponent(id)}`); void refresh(); setToast('Bowl benchmark created. Follow its progress in this workspace.'); }}/>}
    {toast && <div className="toast" role="status"><Icon name="check" size={18}/><span>{toast}</span><button aria-label="Dismiss notification" onClick={() => setToast('')}><Icon name="close" size={16}/></button></div>}
  </div>;
}

function Overview({ rows, batches, benchmarks, benchmarksLoaded, loading, error, retry }: {
  rows: CampaignRow[]; batches: ProjectBatch[] | null; benchmarks: Campaign[]; benchmarksLoaded: boolean;
  loading: boolean; error: string; retry: () => void;
}) {
  return <>
    <SectionHeading title="Investigation workspace" description="Manage your prototype, run tests and inspect the results." action={<a className="button primary" href="#/projects/new"><Icon name="plus" size={18}/>New project</a>}/>
    <section className="project-entry-banner"><div><h3>Projects</h3><p>Keep each prototype’s models, inputs, success criteria and individual run evidence together.</p></div><a className="button secondary" href="#/projects">Open projects<Icon name="chevron" size={16}/></a></section>
    <div className="metrics-grid">
      <Metric icon="campaign" title="Project campaigns" value={batches?.length ?? '—'} detail="Suites, sweeps and environment matrices"/>
      <Metric icon="layers" title="Project runs completed" value={batches?.reduce((sum, item) => sum + item.completed, 0) ?? '—'} detail="Across saved project campaigns"/>
      <Metric icon="search" title="Bowl benchmarks" value={benchmarksLoaded ? benchmarks.length : '—'} detail="LIBERO and synthetic campaigns"/>
      <Metric icon="runtime" title="Benchmark episodes" value={benchmarksLoaded ? benchmarks.reduce((sum, item) => sum + (item.budget?.completed ?? 0), 0) : '—'} detail="Completed benchmark attempts"/>
    </div>
    <section className="card"><div className="card-heading"><div><h3>Recent campaigns</h3><p>Compare a project's test conditions or revisit a bowl benchmark.</p></div>
      <div className="campaign-overview-actions"><a className="text-link" href="#/campaigns">View all campaigns</a><NewCampaignLink/></div></div>
      {error && <div className="card-pad"><Notice tone="warning">{error} <button className="project-inline-button" onClick={retry}>Retry</button></Notice></div>}
      {loading && <Loading/>}
      {rows.length ? <CampaignTable rows={rows.slice(0, 5)}/> : !error && !loading && <Empty title="No campaigns yet">Choose New campaign to test a project across several conditions.</Empty>}
    </section>
  </>;
}

function Metric({ icon, title, value, detail }: { icon: 'campaign' | 'layers' | 'search' | 'runtime'; title: string; value: number | string; detail: string }) {
  return <section className="metric"><div><span>{title}</span><Icon name={icon} size={18}/></div><strong>{value}</strong><p>{detail}</p></section>;
}

function CampaignDetail({ id, notify }: { id: string; notify: (message: string) => void }) {
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string>();
  const [cancelling, setCancelling] = useState(false);
  const refresh = useCallback(async () => { try { setCampaign(await request<Campaign>(`/campaigns/${encodeURIComponent(id)}`)); setError(''); } catch (e) { setError((e as Error).message); } }, [id]);
  useEffect(() => { setCampaign(null); void refresh(); const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 2500); return () => clearInterval(timer); }, [refresh]);
  if (!campaign) return error ? <Notice tone="error">{error}</Notice> : <Loading/>;
  const candidates = campaign.candidates ?? [], budget = campaign.budget;
  const selectedCandidate = candidates.find(c => c.id === selected);
  const activeJob = campaign.jobs?.find(j => activeCampaignStatus(j.status));
  async function cancel() { if (!activeJob) return; setCancelling(true); try { await post(`/jobs/${encodeURIComponent(activeJob.id)}/cancel`); notify('Cancellation requested. The worker will stop at a safe execution boundary.'); void refresh(); } catch (e) { setError((e as Error).message); } finally { setCancelling(false); } }
  async function resume(jobId: string) { setCancelling(true); try { await post(`/jobs/${encodeURIComponent(jobId)}/resume`); notify('Interrupted job queued to resume within its existing allowance.'); void refresh(); } catch (e) { setError((e as Error).message); } finally { setCancelling(false); } }
  return <><a className="back-link" href="#/campaigns">All campaigns</a><SectionHeading eyebrow="CAMPAIGN INVESTIGATION" title={campaign.name} description={`${methodName(campaign.spec.method)} · Seed ${campaign.spec.seed} · Created ${formatTime(campaign.created_at)}`} action={<div className="analysis-actions">
    <HelpTutorial title="Campaign tutorial" steps={campaignDetailGuide(campaign)}/>
    {activeJob && <button className="button secondary" onClick={() => void cancel()} disabled={cancelling}><Icon name="stop" size={16}/>{cancelling ? 'Cancelling…' : 'Cancel active job'}</button>}
  </div>}/><div className="detail-badges"><Status value={campaign.status}/><BackendBadge backend={campaign.backend}/><span className="mono muted small">{shortId(campaign.id)}</span></div>{campaign.backend === 'synthetic' && <Notice>Synthetic validation. All outcomes and traces in this campaign are generated test data. They do not measure robot performance.</Notice>}{error && <Notice tone="error">{error}</Notice>}
    <div className="campaign-layout"><section className="card domain-card"><div className="card-heading"><div><h3>Measured scene changes</h3><p>Each point is a proposed configuration on the two search states.</p></div><span className="small muted">{candidates.length} / {campaign.spec.candidate_count} proposals</span></div><ScatterPlot candidates={candidates} domain={campaign.spec.domain ?? defaultDomain} selected={selected} onSelect={setSelected}/><div className="chart-note"><Icon name="info" size={16}/>{selectedCandidate ? `Selected: camera ${(selectedCandidate.scene_change.main_camera_dx_m * 100).toFixed(3)} cm · light ${selectedCandidate.scene_change.light_scale.toFixed(4)}× · ${label(selectedCandidate.status)}` : 'Measured points only. Blank regions have not been evaluated.'}</div></section><div className="campaign-right"><section className="card budget-card"><div className="card-heading"><h3>Episode budget</h3><Icon name="layers" size={19}/></div><div className="budget-count" data-tour="campaign-progress"><strong>{budget?.completed ?? 0}</strong><span>/ {(budget?.limits.baseline ?? 0) + (budget?.limits.search ?? 0) + (budget?.limits.reduction ?? 0) + (budget?.limits.confirmation ?? 0) + (budget?.limits.rerun ?? 0)}<small>completed episodes</small></span></div><div className="budget-progress"><i style={{ width: `${Math.min(100, (budget?.completed ?? 0) / Math.max(1, (budget?.limits.baseline ?? 0) + (budget?.limits.search ?? 0) + (budget?.limits.reduction ?? 0) + (budget?.limits.confirmation ?? 0) + (budget?.limits.rerun ?? 0)) * 100)}%` }}/></div><dl className="definition-list"><div><dt>Reference checks</dt><dd>{budget?.limits.baseline ?? 0}</dd></div><div><dt>Search allowance</dt><dd>{budget?.limits.search ?? '—'}</dd></div><div><dt>Reduction allowance</dt><dd>{budget?.limits.reduction ?? '—'}</dd></div><div><dt>Confirmation allowance</dt><dd>{budget?.limits.confirmation ?? '—'}</dd></div><div><dt>Fresh rerun allowance</dt><dd>{budget?.limits.rerun ?? 0}</dd></div><div className="divider"><dt>Attempts charged</dt><dd>{budget?.attempted ?? 0} / {budget?.limits.max_attempts ?? '—'}</dd></div><div><dt>Reserved</dt><dd>{budget?.reserved ?? 0}</dd></div><div><dt>Infrastructure retries</dt><dd>{budget?.retries ?? 0} / 2</dd></div></dl></section><section className="card case-links"><div className="card-heading"><h3>Selected witnesses</h3><span className="count-pill">{campaign.cases?.length ?? 0}</span></div>{campaign.cases?.length ? campaign.cases.map((c, index) => <a className="case-link" data-tour={index === 0 ? 'campaign-witness' : undefined} key={c.id} href={`#/cases/${encodeURIComponent(c.id)}`}><span><strong>Witness {index + 1}</strong><small>{c.status ? label(c.status) : shortId(c.id)}</small></span><Icon name="chevron" size={18}/></a>) : <p>No witness selected yet. A valid search may finish without finding a failure.</p>}</section></div></div>
    <section className="card"><div className="card-heading"><div><h3>Candidate record</h3><p>Complete paired outcomes are required before a candidate receives a score.</p></div></div>{candidates.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Candidate</th><th>Camera Δx</th><th>Lighting</th><th>Failed search states</th><th>Proposal source</th><th>Status</th></tr></thead><tbody>{candidates.map((c, index) => <tr key={c.id} className={selected === c.id ? 'selected-row' : ''}><td><button className="table-button mono" data-tour={index === 0 ? 'campaign-candidate' : undefined} onClick={() => setSelected(c.id)}>#{String((c.proposal_index ?? c.index ?? index) + 1).padStart(2, '0')}</button></td><td className="mono">{(c.scene_change.main_camera_dx_m * 100).toFixed(3)} cm</td><td className="mono">{c.scene_change.light_scale.toFixed(4)}×</td><td>{candidateFailureCount(c) ?? '—'} / 2</td><td>{label(c.source ?? c.reason ?? campaign.spec.method)}</td><td><Status value={c.status}/></td></tr>)}</tbody></table></div> : <Empty title="Waiting for the first proposal">The worker records proposals and outcomes as the campaign runs.</Empty>}</section>
    <CampaignEvidence key={campaign.id} campaign={campaign}/>
    {campaign.jobs?.length ? <section className="card jobs-card"><div className="card-heading" data-tour="campaign-jobs"><h3>Execution jobs</h3></div>{campaign.jobs.map(job => <div className="job-row" key={job.id}><Icon name="terminal" size={18}/><div><strong>{label(job.kind ?? job.phase ?? 'campaign')}</strong><span className="mono">{shortId(job.id)}</span>{job.error && <p className="text-red">{job.error}</p>}</div><Status value={job.status}/>{job.status === 'interrupted' && <button className="button secondary" disabled={cancelling || Boolean(activeJob)} onClick={() => void resume(job.id)}><Icon name="refresh" size={15}/>Resume job</button>}</div>)}</section> : null}
  </>;
}

function Runtime({ health, catalog, connected, refresh }: { health: Health | null; catalog: Catalog | null; connected: boolean | null; refresh: () => Promise<void> }) {
  return <><SectionHeading eyebrow="EXECUTION ENVIRONMENT" title="Runtime & setup" description="Check campaign worker connections and robot qualification on the execution host." action={<button className="button secondary" onClick={() => void refresh()}><Icon name="refresh" size={17}/>Refresh status</button>}/><div className="runtime-grid"><section className="card"><div className="card-heading"><h3>Service connection</h3><Status value={connected ? 'ready' : 'offline'}/></div><dl className="definition-list runtime-definitions"><div><dt>API</dt><dd>{connected === null ? 'Connecting' : connected ? 'Connected' : 'Disconnected'}</dd></div>{(['libero', 'synthetic'] as const).map(backend => { const worker = workerFor(health, backend); return <div key={backend}><dt>{backend === 'libero' ? 'Robot worker' : 'Synthetic worker'}</dt><dd>{worker?.online ? 'Online' : 'Offline'}{worker?.last_seen ? ` · ${formatTime(worker.last_seen)}` : ''}</dd></div>; })}<div><dt>Robot qualification</dt><dd>{health?.readiness.qualified ? 'Qualified' : 'Not verified'}</dd></div></dl><div className="card-pad"><Notice tone={health?.readiness.qualified ? 'info' : 'warning'}>{health?.readiness.reason ?? 'Connect the API to inspect worker readiness. Robot execution stays unavailable until target-host checks pass.'}</Notice></div></section><section className="card"><div className="card-heading"><h3>Pinned experiment</h3><Icon name="file" size={19}/></div><dl className="definition-list runtime-definitions"><div><dt>Policy</dt><dd>{catalog?.policy.repo_id ?? 'Available when API connects'}</dd></div><div><dt>Snapshot</dt><dd className="mono wrap-anywhere">{catalog?.policy.revision ?? '—'}</dd></div><div><dt>Task suite</dt><dd>{catalog?.task.suite ?? 'LIBERO'}</dd></div><div><dt>Task</dt><dd>{catalog?.task.name ? label(catalog.task.name) : 'Available when API connects'}</dd></div><div><dt>Camera domain</dt><dd>−4 to +4 cm</dd></div><div><dt>Lighting domain</dt><dd>0.70 to 1.30×</dd></div></dl></section></div><section className="card setup-card"><div className="card-heading"><div><h3>Workspace and execution host</h3><p>The browser reads evidence through the API. The simulator lives on the execution host.</p></div></div><div className="setup-columns"><div><div className="setup-icon"><Icon name="terminal" size={24}/></div><h3>In the workspace</h3><p>Run the API and frontend, validate the application with synthetic episodes, and inspect saved investigations.</p><ul><li>Search proposals and deterministic validation</li><li>Budgeting, job recovery, and artifact validation</li><li>Case comparison, reduction, and exports</li></ul><span className="setup-tag">No robotics GPU required</span></div><div><div className="setup-icon orange"><Icon name="runtime" size={24}/></div><h3>On your RTX 5090 PC</h3><p>Install the pinned robotics environment and establish the reference before collecting scientific evidence.</p><ul><li>Validate CUDA and both camera render paths</li><li>Qualify policy behavior and initial-state resets</li><li>Verify scene changes and run real campaigns</li></ul><span className="setup-tag">Linux runtime · GPU inference</span></div></div></section><Notice>Setup commands and qualification steps are in the repository README. Synthetic campaign results are always labeled and cannot establish robot readiness.</Notice></>;
}



