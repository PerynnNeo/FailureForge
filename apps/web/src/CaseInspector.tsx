import { useCallback, useEffect, useRef, useState } from 'react';
import { artifactUrl, formatTime, label, post, request, shortId } from './api';
import { BackendBadge, Empty, Icon, Loading, Notice, SectionHeading, Status } from './components';
import { TraceChart } from './Charts';
import type { Episode, FailureCase } from './types';
import { caseActionAvailability, collectCasePairs, evidencePairKey } from './caseWorkflow';

type Tab = 'evidence' | 'reduction' | 'confirmation' | 'provenance';
type TracePayload = { times?: number[]; actions?: number[][]; success?: boolean[]; diagnostic_state?: number[][]; samples?: Array<Record<string, unknown>>; steps?: number[] | number };

export default function CaseInspector({ id, notify }: { id: string; notify: (message: string) => void }) {
  const [item, setItem] = useState<FailureCase | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [tab, setTab] = useState<Tab>('evidence');
  const [selectedPairKey, setSelectedPairKey] = useState('');
  const [camera, setCamera] = useState<'main' | 'wrist'>('main');
  const [traceEpisode, setTraceEpisode] = useState('changed');
  const [samples, setSamples] = useState<Array<Record<string, unknown>>>([]);
  const [traceError, setTraceError] = useState('');
  const [traceBusy, setTraceBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [playbackError, setPlaybackError] = useState('');
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const referenceVideo = useRef<HTMLVideoElement>(null), changedVideo = useRef<HTMLVideoElement>(null);
  const refresh = useCallback(async () => { try { setItem(await request<FailureCase>(`/cases/${encodeURIComponent(id)}`)); setError(''); } catch (e) { setError((e as Error).message); } }, [id]);
  useEffect(() => { setItem(null); void refresh(); const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 3000); return () => clearInterval(timer); }, [refresh]);
  const episodes = item?.episodes ?? [];
  const pairs = collectCasePairs(item);
  const pair = pairs.find(candidate => evidencePairKey(candidate) === selectedPairKey) ?? pairs[0];
  const reference = resolveEpisode(pair?.reference ?? pair?.reference_episode_id, episodes);
  const changed = resolveEpisode(pair?.changed ?? pair?.changed_episode_id, episodes);
  const traceId = (traceEpisode === 'changed' ? changed : reference)?.id;
  useEffect(() => { setPlaying(false); setTime(0); setDuration(0); setPlaybackError(''); }, [camera, reference?.id, changed?.id]);
  useEffect(() => {
    let valid = true; setSamples([]); setTraceError('');
    if (!traceId) return;
    setTraceBusy(true);
    void request<TracePayload>(`/episodes/${encodeURIComponent(traceId)}/trace`).then(data => {
      if (!valid) return;
      if (data.samples) setSamples(data.samples);
      else if (data.actions) setSamples(data.actions.map((action, step) => ({ step, action_l2_norm: Math.sqrt(action.reduce((sum, v) => sum + v * v, 0)) })));
      else if (data.diagnostic_state) setSamples(data.diagnostic_state.map((state, step) => ({ step, diagnostic_progress: state[0], diagnostic_response: state[1], lighting_multiplier: state[2] })));
    }).catch(e => { if (valid) setTraceError((e as Error).message); }).finally(() => { if (valid) setTraceBusy(false); });
    return () => { valid = false; };
  }, [traceId]);
  async function action(kind: 'reduce' | 'confirm' | 'rerun') {
    setBusy(kind); setError('');
    try { await post(`/cases/${encodeURIComponent(id)}/${kind}`, kind === 'rerun' ? { allowance: 2 } : {}, crypto.randomUUID()); notify(kind === 'rerun' ? 'Fresh paired rerun queued with its own two-episode allowance.' : `${kind === 'reduce' ? 'Reduction' : 'Confirmation'} job queued.`); await refresh(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(''); }
  }
  async function togglePlayback() {
    const videos = [referenceVideo.current, changedVideo.current].filter((v): v is HTMLVideoElement => Boolean(v));
    if (playing) { videos.forEach(v => v.pause()); setPlaying(false); return; }
    if (time >= duration && duration > 0) { videos.forEach(v => { v.currentTime = 0; }); setTime(0); }
    try { await Promise.all(videos.map(v => v.play())); setPlaying(true); setPlaybackError(''); }
    catch { videos.forEach(v => v.pause()); setPlaying(false); setPlaybackError('A recording could not be played. Check that its artifact is available.'); }
  }
  function syncTime(source: HTMLVideoElement) {
    setTime(source.currentTime);
    const other = source === referenceVideo.current ? changedVideo.current : referenceVideo.current;
    if (other && Math.abs(other.currentTime - source.currentTime) > .15) other.currentTime = Math.min(source.currentTime, Number.isFinite(other.duration) ? other.duration : source.currentTime);
  }
  function scrub(value: number) { setTime(value); [referenceVideo.current, changedVideo.current].forEach(v => { if (v) v.currentTime = Math.min(value, Number.isFinite(v.duration) ? v.duration : value); }); }
  if (!item) return error ? <Notice tone="error">{error}</Notice> : <Loading/>;
  const availability = caseActionAvailability(item.jobs ?? []);
  const displayedJob = availability.active ?? availability.latest;
  const hasVideo = Boolean(artifactUrl(reference?.artifacts?.[camera === 'main' ? 'main_video' : 'wrist_video']) || artifactUrl(changed?.artifacts?.[camera === 'main' ? 'main_video' : 'wrist_video']));
  return <><a className="back-link" href={`#/campaigns/${encodeURIComponent(item.campaign_id)}`}>Back to campaign</a><SectionHeading eyebrow="CASE INVESTIGATION" title="Inspect the failure. Keep the evidence." description={`Case ${shortId(item.id)}${item.created_at ? ` · ${formatTime(item.created_at)}` : ''}`} action={<a className="button primary" href={`/api/cases/${encodeURIComponent(item.id)}/export`} download><Icon name="download" size={17}/>Export evidence</a>}/><div className="detail-badges"><Status value={item.status}/><BackendBadge backend={item.backend}/><span className="small muted">Observed failures on search states: {item.failure_state_ids?.join(', ') || 'None'}</span></div>{item.backend === 'synthetic' && <Notice>Synthetic validation case. These generated outcomes and traces test the application; they are not robot evidence. No simulated robot video is substituted.</Notice>}{error && <Notice tone="error">{error}</Notice>}
    <div className="case-summary"><div><span>Camera displacement</span><strong>{(item.scene_change.main_camera_dx_m * 100).toFixed(3)}<small>cm</small></strong></div><div><span>Lighting multiplier</span><strong>{item.scene_change.light_scale.toFixed(4)}<small>×</small></strong></div><div><span>Preserved failure states</span><strong>{item.failure_state_ids?.length ?? 0}<small>/ 2</small></strong></div><div className="case-actions"><button className="button secondary" disabled={Boolean(busy) || !availability.canReduce} title={availability.reductionRequested ? 'Reduction allowance already requested; manage the existing job in the campaign.' : availability.confirmationRequested ? 'The case configuration is frozen after confirmation is requested.' : undefined} onClick={() => void action('reduce')}><Icon name="sliders" size={16}/>{busy === 'reduce' ? 'Queuing…' : 'Reduce witness'}</button><button className="button secondary" disabled={Boolean(busy) || !availability.canConfirm} title={availability.confirmationRequested ? 'Confirmation allowance already requested; manage the existing job in the campaign.' : undefined} onClick={() => void action('confirm')}><Icon name="check" size={16}/>{busy === 'confirm' ? 'Queuing…' : 'Confirm case'}</button><button className="button secondary" disabled={Boolean(busy) || !availability.canRerun} onClick={() => void action('rerun')}><Icon name="refresh" size={16}/>{busy === 'rerun' ? 'Queuing…' : 'Fresh paired rerun'}</button></div></div>
    {displayedJob && <div className="case-job-state" role="status"><Icon name="terminal" size={18}/><div><strong>{availability.active ? 'Current job' : 'Latest job'}: {label(displayedJob.kind)}</strong><span>{availability.active ? 'Additional case actions are unavailable while this campaign has active work.' : availability.confirmationRequested ? 'Confirmation was requested. The selected configuration is frozen; fresh paired reruns remain available.' : availability.reductionRequested ? 'Reduction already has an allocated job. Manage or resume that job from the campaign.' : 'Manage cancellation and interrupted-job recovery in the campaign.'}</span>{displayedJob.error && <span className="text-red">{displayedJob.error}</span>}</div><Status value={displayedJob.status}/><a className="text-link" href={`#/campaigns/${encodeURIComponent(item.campaign_id)}`}>Manage jobs</a></div>}<div className="tabs" role="tablist" aria-label="Case sections">{(['evidence', 'reduction', 'confirmation', 'provenance'] as Tab[]).map(t => <button key={t} role="tab" id={`tab-${t}`} aria-controls={`panel-${t}`} aria-selected={tab === t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{label(t)}</button>)}</div>
    <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
      {tab === 'evidence' && <>
        <section className="card evidence-card"><div className="card-heading"><div><h3>Matched execution comparison</h3><p>Same initial state and seed schedule. Reference and changed scene.</p></div><div className="evidence-controls"><select aria-label="Paired evidence state" value={pair ? evidencePairKey(pair) : ''} onChange={e => setSelectedPairKey(e.target.value)}>{pairs.length ? pairs.map(p => <option key={evidencePairKey(p)} value={evidencePairKey(p)}>State {p.state_id}{p.phase ? ` · ${label(p.phase)}` : ''}</option>) : <option value="">No paired evidence yet</option>}</select><div className="segmented" aria-label="Camera view"><button className={camera === 'main' ? 'selected' : ''} aria-pressed={camera === 'main'} onClick={() => setCamera('main')}>Main</button><button className={camera === 'wrist' ? 'selected' : ''} aria-pressed={camera === 'wrist'} onClick={() => setCamera('wrist')}>Wrist</button></div></div></div><div className="video-pair">{[{ episode: reference, condition: 'Reference', ref: referenceVideo }, { episode: changed, condition: 'Changed scene', ref: changedVideo }].map(({ episode, condition, ref }) => {
          const url = artifactUrl(episode?.artifacts?.[camera === 'main' ? 'main_video' : 'wrist_video']);
          return <div className="video-panel" key={condition}><div className="video-label"><span><i className={condition === 'Reference' ? 'reference-key' : 'changed-key'}/>{condition}</span>{episode && <Status value={episode.outcome ?? episode.status}/>}</div><div className="video-surface">{url ? <video key={url} ref={ref} src={url} playsInline preload="metadata" onLoadedMetadata={e => { const seconds = e.currentTarget.duration; if (Number.isFinite(seconds)) setDuration(previous => Math.max(previous, seconds)); }} onTimeUpdate={e => { const leader = (referenceVideo.current?.duration ?? 0) >= (changedVideo.current?.duration ?? 0) ? referenceVideo.current : changedVideo.current; if (e.currentTarget === leader) syncTime(e.currentTarget); }} onEnded={e => { if (e.currentTarget.duration >= duration - .1) setPlaying(false); }} onError={() => setPlaybackError('A video artifact could not be loaded. The evidence export may provide additional diagnostics.')} aria-label={`${condition}, ${camera} camera recording`}/> : <div className="video-empty"><Icon name="camera" size={30}/><strong>{item.backend === 'synthetic' ? 'No robot recording' : 'Recording unavailable'}</strong><span>{item.backend === 'synthetic' ? 'Synthetic validation produces numerical evidence.' : episode ? 'This execution has no recording for the selected camera.' : 'Run a paired verification to collect this condition.'}</span></div>}</div><div className="video-caption"><span>{episode ? `${episode.steps} control steps · ${episode.elapsed_seconds.toFixed(2)} s execution` : 'No execution selected'}</span><span className="mono">{episode ? shortId(episode.id) : '—'}</span></div></div>;
        })}</div>{hasVideo && <div className="playback-controls"><button className="icon-button" aria-label={playing ? 'Pause both recordings' : 'Play both recordings'} onClick={() => void togglePlayback()}><Icon name={playing ? 'pause' : 'play'} size={18}/></button><span className="mono small">{time.toFixed(1)} s</span><input aria-label="Synchronized recording position" type="range" min="0" max={duration || 1} step="0.05" value={time} onChange={e => scrub(Number(e.target.value))}/><span className="mono small">{duration.toFixed(1)} s</span><span className="playback-note">Synchronized playback</span></div>}{playbackError && <div className="card-pad"><Notice tone="error">{playbackError}</Notice></div>}</section>
        <section className="card trace-card"><div className="card-heading"><div><h3>{item.backend === 'synthetic' ? 'Synthetic diagnostic trace' : 'Action trace'}</h3><p>{item.backend === 'synthetic' ? 'Generated diagnostic state at each recorded step.' : 'Action magnitude at each recorded control step.'}</p></div><div className="segmented"><button className={traceEpisode === 'reference' ? 'selected' : ''} onClick={() => setTraceEpisode('reference')}>Reference</button><button className={traceEpisode === 'changed' ? 'selected' : ''} onClick={() => setTraceEpisode('changed')}>Changed</button></div></div><div className="card-pad">{traceBusy ? <Loading/> : traceError ? <p className="muted small">{traceError}</p> : samples.length ? <TraceChart samples={samples}/> : <p className="muted">No trace is available for this selected execution yet.</p>}</div></section>
        <Notice>Fresh paired rerun schedules two new executions with a separate allowance. Recorded playback does not execute the policy. Different outcomes are preserved alongside the original evidence.</Notice>
      </>}
      {tab === 'reduction' && <section className="card"><div className="card-heading"><div><h3>Witness reduction history</h3><p>A proposal is accepted only when the frozen failing search states still fail.</p></div></div>{item.reduction_history?.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Proposal</th><th>Camera Δx</th><th>Lighting</th><th>Decision</th><th>Evidence</th></tr></thead><tbody>{item.reduction_history.map((entry, index) => { const scene = (entry.scene_change ?? entry.proposal ?? {}) as Record<string, unknown>; return <tr key={index}><td className="mono">{index + 1}</td><td className="mono">{typeof scene.main_camera_dx_m === 'number' ? `${(scene.main_camera_dx_m * 100).toFixed(3)} cm` : '—'}</td><td className="mono">{typeof scene.light_scale === 'number' ? `${scene.light_scale.toFixed(4)}×` : '—'}</td><td><Status value={typeof entry.accepted === 'boolean' ? entry.accepted ? 'accepted' : 'rejected' : String(entry.status ?? 'evaluated')}/></td><td>{entry.reason ? String(entry.reason) : entry.failure_state_ids ? `Failed states: ${String(entry.failure_state_ids)}` : 'Recorded in export'}</td></tr>; })}</tbody></table></div> : <Empty icon="sliders" title="No reduction run yet">Reduction first verifies the original witness, then tests smaller changes within the shared 32-episode allowance.</Empty>}</section>}
      {tab === 'confirmation' && <section className="card"><div className="card-heading"><div><h3>Held-out confirmation</h3><p>Reference and changed outcomes on the untouched confirmation state bank.</p></div></div>{item.confirmation_summary && Object.keys(item.confirmation_summary).length ? <div className="confirmation-content"><dl className="definition-list">{Object.entries(item.confirmation_summary).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl><Notice>These are paired outcomes on the declared confirmation states. Their counts do not establish a population failure probability.</Notice></div> : <Empty icon="check" title="Confirmation has not run">Freeze the final configuration, then compare reference and changed executions on ten held-out states.</Empty>}</section>}
      {tab === 'provenance' && <section className="card"><div className="card-heading"><div><h3>Case provenance</h3><p>The exported bundle contains the full manifest and payload checksums.</p></div></div><dl className="definition-list provenance-list"><div><dt>Case identity</dt><dd className="mono wrap-anywhere">{item.id}</dd></div><div><dt>Parent campaign</dt><dd><a href={`#/campaigns/${encodeURIComponent(item.campaign_id)}`}>{item.campaign_id}</a></dd></div><div><dt>Execution backend</dt><dd><BackendBadge backend={item.backend}/></dd></div><div><dt>Case status</dt><dd><Status value={item.status}/></dd></div><div><dt>Failure witness states</dt><dd>{item.failure_state_ids?.join(', ') || 'None'}</dd></div><div><dt>Evidence episodes available</dt><dd>{episodes.length}</dd></div><div><dt>Selected camera displacement</dt><dd className="mono">{item.scene_change.main_camera_dx_m} m</dd></div><div><dt>Selected light multiplier</dt><dd className="mono">{item.scene_change.light_scale}</dd></div></dl><div className="card-pad"><Notice>Inspect each episode’s initial state, seed, outcome, trace, and recordings in the export. Payload hashes verify file integrity; robot reproducibility requires fresh execution on a qualified runtime.</Notice></div></section>}
    </div>
  </>;
}

function resolveEpisode(value: string | Episode | undefined, episodes: Episode[]): Episode | undefined { return typeof value === 'string' ? episodes.find(e => e.id === value) : value; }



