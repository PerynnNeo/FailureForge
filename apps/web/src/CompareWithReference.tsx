import { useEffect, useRef, useState } from 'react';
import { label, request } from './api';
import { Icon, Loading, Notice } from './components';
import type { Inputs, RunDetail } from './analysisInputs';
import { measuredNumber } from './recordedFields';
import { synchronizeCameras } from './cameraPlayback';
import { useCameraReplay } from './ProjectCameraReplay';
import type { Replay, View } from './ProjectCameraReplay';
import { changedInputs, defaultPair, resolvePair } from './campaignCompare';
import type { Condition } from './campaignCompare';
import { coordinateValue, verdict } from './campaignVerdict';
import './compareWithReference.css';

const active = (status: string) => status === 'running' || status === 'queued';

/** Fetch a single run's full detail, guarded against races and stale paths. */
function useRunDetail(path: string) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let current = true, timer = 0;
    setDetail(null); setError('');
    async function load() {
      try {
        const data = await request<RunDetail>(path);
        if (!current) return;
        setDetail(data);
        if (active(data.status)) timer = window.setTimeout(() => void load(), 2000);
      } catch (failure) { if (current) setError((failure as Error).message); }
    }
    if (path) void load();
    return () => { current = false; window.clearTimeout(timer); };
  }, [path]);
  return { detail, error };
}

function runVerdict(run: Condition, detail: RunDetail | null) {
  if (!detail) return verdict(run);
  if (detail.assessment_error) return 'Inconclusive';
  if (detail.status !== 'completed') return label(detail.status);
  const passed = detail.result?.passed ?? (detail.result?.summary as Inputs | undefined)?.validation_passed;
  return typeof passed === 'boolean' ? (passed ? 'Passed' : 'Failed') : 'Measurement only';
}

function verdictClass(text: string) {
  return text === 'Passed' ? 'text-green' : text === 'Failed' ? 'text-red' : undefined;
}

/** Measured result + acceptance limit + verdict for one run, mirroring RunVisual's NumericalSummary. */
function RunResult({ run, detail }: { run: Condition; detail: RunDetail | null }) {
  const outcome = runVerdict(run, detail);
  const result = (detail?.result ?? undefined) as Inputs | undefined;
  const metrics = (result?.summary ?? result?.metrics ?? result ?? run.metrics) as Inputs;
  const scalars = Object.entries(metrics).filter(([, value]) => typeof value === 'number' && Number.isFinite(value));
  const criteria = (result?.criteria ?? {}) as Inputs;
  const checks = Object.entries(criteria).filter(([, value]) => typeof value === 'boolean');
  const limits = Object.entries(criteria).filter(([, value]) => typeof value === 'number' && Number.isFinite(value));
  return <div className="compare-run-result">
    <h5>{run.label}</h5>
    <p className="compare-verdict">Verdict · <strong className={verdictClass(outcome)}>{outcome}</strong></p>
    {run.error && <p className="small muted">{run.error}</p>}
    {scalars.length > 0 && <><h6>Measured result</h6>
      <dl className="analysis-metrics">{scalars.map(([name, value]) => <div key={name}>
        <dt>{label(name)}</dt><dd>{measuredNumber(value as number)}</dd></div>)}</dl></>}
    {(checks.length > 0 || limits.length > 0) && <><h6>Acceptance limit</h6>
      {checks.length > 0 && <ul className="matrix-checks">{checks.map(([name, passed]) => <li key={name}>{label(name)}
        <strong className={'matrix-tag ' + (passed ? 'passed' : 'failed')}>{passed ? 'Passed' : 'Failed'}</strong></li>)}</ul>}
      {limits.length > 0 && <dl className="analysis-metrics">{limits.map(([name, value]) => <div key={name}>
        <dt>{label(name)}</dt><dd>{measuredNumber(value as number)}</dd></div>)}</dl>}</>}
    {!scalars.length && !checks.length && !limits.length && !run.error &&
      <p className="small muted">No measured result recorded for this condition.</p>}
  </div>;
}

function replayState(replay: Replay | null, requestError: string) {
  const ready = replay?.status === 'ready' && !requestError;
  const main = replay?.views?.find((view: View) => view.id === 'main');
  const hasFootage = ready && Boolean(main);
  const message = requestError || replay?.description || 'Checking camera views for this run…';
  return { hasFootage, main, message };
}

/** Side-by-side main views driven on one shared timeline when both runs have footage. */
function ComparePlayers({ leftPath, rightPath }: { leftPath: string; rightPath: string }) {
  const left = useCameraReplay(leftPath + '/camera-replay', true);
  const right = useCameraReplay(rightPath + '/camera-replay', true);
  const leftVideo = useRef<HTMLVideoElement>(null), rightVideo = useRef<HTMLVideoElement>(null);
  const playback = useRef<ReturnType<typeof synchronizeCameras> | null>(null);
  const [playbackError, setPlaybackError] = useState('');

  const leftState = replayState(left.replay, left.requestError);
  const rightState = replayState(right.replay, right.requestError);
  const synced = leftState.hasFootage && rightState.hasFootage;

  useEffect(() => {
    if (!synced || !leftVideo.current || !rightVideo.current) return;
    setPlaybackError('');
    const sync = synchronizeCameras(leftVideo.current, rightVideo.current,
      () => setPlaybackError('The browser could not play both camera views.'));
    playback.current = sync;
    return () => { sync.disconnect(); playback.current = null; };
  }, [synced, leftState.main?.url, rightState.main?.url]);

  const sides: Array<{ key: 'left' | 'right'; title: string; state: ReturnType<typeof replayState>;
    ref: typeof leftVideo; retry: () => void }> = [
    { key: 'left', title: 'Reference run', state: leftState, ref: leftVideo, retry: left.retry },
    { key: 'right', title: 'Comparison run', state: rightState, ref: rightVideo, retry: right.retry },
  ];
  return <section className="compare-players" aria-label="Side-by-side camera replay">
    <div className="compare-video-pair">{sides.map(side =>
      <figure key={side.key}><figcaption>{side.title}</figcaption>
        {side.state.hasFootage && side.state.main
          ? <video ref={side.ref} src={side.state.main.url} aria-label={side.title + ' camera replay'}
              controls playsInline muted preload="auto"/>
          : <p className="compare-replay-status" role="status">{side.state.message}
              {(side.state.message && !side.state.hasFootage) && <> <button type="button" className="project-inline-button" onClick={side.retry}>Retry</button></>}
            </p>}
      </figure>)}</div>
    {synced && <div className="project-camera-actions">
      <span>Both runs play on one shared timeline.</span>
      <button className="project-inline-button" type="button" disabled={Boolean(playbackError)} onClick={() => playback.current?.restart()}>
        <Icon name="refresh" size={14}/>Restart both runs</button>
    </div>}
    {playbackError && <p role="alert">{playbackError}</p>}
  </section>;
}

export function CompareWithReference({ base, runs, field, reference }: {
  base: string; runs: Condition[]; field?: string | null; reference?: Condition;
}) {
  const completed = runs.filter(run => run.status === 'completed');
  const [pair, setPair] = useState(() => defaultPair(runs, reference?.id));
  const { left, right } = resolvePair(runs, pair);

  const leftPath = left ? base + '/' + encodeURIComponent(left.id) : '';
  const rightPath = right ? base + '/' + encodeURIComponent(right.id) : '';
  const leftDetail = useRunDetail(leftPath);
  const rightDetail = useRunDetail(rightPath);

  // Diff prefers loaded inputs, falling back to coordinates so it renders before details arrive.
  const leftInputs = leftDetail.detail?.inputs ?? left?.coordinates;
  const rightInputs = rightDetail.detail?.inputs ?? right?.coordinates;
  const changes = left && right ? changedInputs(leftInputs, rightInputs) : [];

  if (completed.length < 2) return <p className="small muted">At least two completed conditions are needed to compare.</p>;

  function picker(side: 'left' | 'right', value: string | null) {
    return <label className="project-field"><span>{side === 'left' ? 'Reference' : 'Comparison'}</span>
      <select value={value ?? ''} onChange={event => setPair(prev => ({ ...prev, [side]: event.target.value }))}>
        {completed.map(run => <option key={run.id} value={run.id}>{run.label}{run.reference ? ' · Reference' : ''}</option>)}
      </select></label>;
  }

  const error = leftDetail.error || rightDetail.error;
  return <div className="compare-panel">
    <div className="compare-pickers">{picker('left', pair.left)}{picker('right', pair.right)}</div>
    {pair.left && pair.left === pair.right && <Notice tone="warning">Pick two different conditions to compare.</Notice>}
    {error && <Notice tone="error">{error}</Notice>}

    <div className="compare-diff">
      <h5>Changed inputs</h5>
      {changes.length === 0
        ? <p className="small muted">No input differences between these conditions.</p>
        : <div className="analysis-table-scroll"><table className="data-table">
            <thead><tr><th>Input</th><th>Reference</th><th>Comparison</th></tr></thead>
            <tbody>{changes.map(change => <tr key={change.key}>
              <td>{label(change.key === 'value' ? field ?? 'input' : change.key)}</td>
              <td>{coordinateValue(change.key, change.left, field)}</td>
              <td>{coordinateValue(change.key, change.right, field)}</td>
            </tr>)}</tbody>
          </table></div>}
    </div>

    <div className="compare-results">
      {left ? <RunResult run={left} detail={leftDetail.detail}/> : <Loading/>}
      {right ? <RunResult run={right} detail={rightDetail.detail}/> : <Loading/>}
    </div>

    {left && right && left.id !== right.id && <ComparePlayers key={left.id + '|' + right.id} leftPath={leftPath} rightPath={rightPath}/>}
  </div>;
}
