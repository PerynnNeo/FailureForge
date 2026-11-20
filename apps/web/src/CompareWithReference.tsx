import { useEffect, useRef, useState } from 'react';
import { label, request } from './api';
import { Icon, Loading, Notice } from './components';
import type { RunDetail } from './analysisInputs';
import { RunResult } from './CampaignRunResult';
import { StationComparison } from './StationComparison';
import { synchronizeCameras } from './cameraPlayback';
import { readMotion } from './motionData';
import { useCameraReplay, useViewportActive } from './ProjectCameraReplay';
import type { Replay, View } from './ProjectCameraReplay';
import { changedInputs, defaultPair, resolvePair } from './campaignCompare';
import type { Condition } from './campaignCompare';
import { coordinateText, coordinateValue } from './campaignVerdict';
import './compareWithReference.css';

/** Only expose the response for the currently selected condition. */
function useRunDetail(path: string) {
  const [response, setResponse] = useState<{path: string; detail: RunDetail | null; error: string}>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    if (path) void request<RunDetail>(path).then(
      detail => { if (current) setResponse({path, detail, error: ''}); },
      failure => { if (current) setResponse({path, detail: null, error: (failure as Error).message}); },
    );
    return () => { current = false; };
  }, [path, attempt]);
  const selected = response?.path === path ? response : undefined;
  return { detail: selected?.detail ?? null, error: selected?.error ?? '', retry: () => setAttempt(n => n + 1) };
}

function replayState(replay: Replay | null, requestError: string) {
  const ready = replay?.status === 'ready' && !requestError;
  const main = replay?.views?.find((view: View) => view.id === 'main');
  const hasFootage = ready && Boolean(main);
  const message = requestError || replay?.description || 'Checking camera views for this run…';
  return { hasFootage, main, message };
}

function recordingDuration(detail: RunDetail | null) {
  if (!detail?.result) return;
  const motion = readMotion(detail.result);
  const times = motion?.kind === 'response' ? motion.logs[0].times : motion?.times;
  return times && times[times.length - 1] - times[0];
}

function ComparePlayers({ leftPath, rightPath, leftDuration, rightDuration, fixedPair }: {
  leftPath: string; rightPath: string; leftDuration?: number; rightDuration?: number; fixedPair: boolean;
}) {
  const container = useRef<HTMLElement>(null);
  const visible = useViewportActive(container);
  const left = useCameraReplay(leftPath + '/camera-replay', visible);
  const right = useCameraReplay(rightPath + '/camera-replay', visible);
  const leftVideo = useRef<HTMLVideoElement>(null), rightVideo = useRef<HTMLVideoElement>(null);
  const playback = useRef<ReturnType<typeof synchronizeCameras> | null>(null);
  const [playbackError, setPlaybackError] = useState('');
  type Side = 'left' | 'right';
  type MediaState = 'loading' | 'playable' | 'failed';
  const [media, setMedia] = useState<Record<Side, MediaState>>({left: 'loading', right: 'loading'});

  const leftState = replayState(left.replay, left.requestError);
  const rightState = replayState(right.replay, right.requestError);
  const synced = leftState.hasFootage && rightState.hasFootage && media.left === 'playable' && media.right === 'playable';

  useEffect(() => {
    if (!synced || !leftVideo.current || !rightVideo.current) return;
    setPlaybackError('');
    const first = leftVideo.current, second = rightVideo.current;
    const sync = synchronizeCameras(first, second,
      () => setPlaybackError('Synchronized playback was interrupted. Restart both runs to try again.'),
      leftDuration && rightDuration ? [leftDuration, rightDuration] : undefined);
    playback.current = sync;
    return () => {
      // Let the decodable side continue if its partner fails during playback.
      sync.disconnect(!(first.error || second.error));
      playback.current = null;
    };
  }, [synced, leftState.main?.url, rightState.main?.url, leftDuration, rightDuration]);

  const sides: Array<{ key: Side; title: string; state: ReturnType<typeof replayState>;
    ref: typeof leftVideo; canRetry: boolean; retry: () => void }> = [
    { key: 'left', title: fixedPair ? 'Passing run' : 'Reference run', state: leftState, ref: leftVideo,
      canRetry: Boolean(left.requestError) || left.replay?.status === 'failed', retry: left.retry },
    { key: 'right', title: fixedPair ? 'Failing run' : 'Comparison run', state: rightState, ref: rightVideo,
      canRetry: Boolean(right.requestError) || right.replay?.status === 'failed', retry: right.retry },
  ];
  const markMedia = (key: Side, status: MediaState) => setMedia(previous => ({ ...previous, [key]: status }));
  return <section ref={container} className="compare-players" aria-label="Side-by-side camera replay">
    <div className="compare-video-pair">{sides.map(side =>
      <figure key={side.key}><figcaption>{side.title}{side.state.main && ' · ' + side.state.main.label}</figcaption>
        {media[side.key] === 'failed' ? <p className="compare-replay-status" role="alert">
          This camera video could not be loaded. <button type="button" className="project-inline-button"
            onClick={() => markMedia(side.key, 'loading')}>Retry video</button></p>
        : side.state.hasFootage && side.state.main
          ? <video ref={side.ref} src={side.state.main.url} aria-label={side.title + ' camera replay'}
              controls playsInline muted preload="auto" onLoadedData={() => markMedia(side.key, 'playable')}
              onError={() => markMedia(side.key, 'failed')}/>
          : <p className="compare-replay-status" role="status">{side.state.message}
              {side.canRetry && <> <button type="button" className="project-inline-button" onClick={side.retry}>Retry</button></>}
            </p>}
        {side.state.hasFootage && <p className="compare-replay-status">{side.state.message}</p>}
      </figure>)}</div>
    {synced && <div className="project-camera-actions">
      <span>{leftDuration && rightDuration ? 'Linked by elapsed time in each recorded run.' : 'Linked by elapsed video time.'}</span>
      <button className="project-inline-button" type="button" onClick={() => { setPlaybackError(''); playback.current?.restart(); }}>
        <Icon name="refresh" size={14}/>Restart both runs</button>
    </div>}
    {synced && playbackError && <p role="alert">{playbackError}</p>}
  </section>;
}

export function CompareWithReference({ base, runs, field, reference, selectedId, fixedPair = false }: {
  base: string; runs: Condition[]; field?: string | null; reference?: Condition; selectedId?: string; fixedPair?: boolean;
}) {
  const completed = runs.filter(run => run.status === 'completed');
  const [pair, setPair] = useState(() => defaultPair(runs, reference?.id, selectedId));
  const { left, right } = resolvePair(runs, pair);

  const leftPath = left ? base + '/' + encodeURIComponent(left.id) : '';
  const rightPath = right ? base + '/' + encodeURIComponent(right.id) : '';
  const leftDetail = useRunDetail(leftPath);
  const rightDetail = useRunDetail(rightPath);

  // Diff from one consistent source for both sides: use full inputs only once BOTH details have
  // loaded, otherwise the campaign-table coordinates. Coordinates are a subset of inputs (only the
  // varied dimensions), so this avoids a mixed-source diff that could flip rows as details arrive.
  const bothLoaded = Boolean(leftDetail.detail && rightDetail.detail);
  // A fixed project recommendation already carries the matched effective scalar input
  // (including an individual joint target and resolved solver defaults).
  const compareDefinitions = bothLoaded && !fixedPair;
  const leftInputs = compareDefinitions ? leftDetail.detail?.inputs : left?.coordinates;
  const rightInputs = compareDefinitions ? rightDetail.detail?.inputs : right?.coordinates;
  const changes = left && right ? changedInputs(leftInputs, rightInputs) : [];

  if (completed.length < 2) return <p className="small muted">At least two completed conditions are needed to compare.</p>;

  function picker(side: 'left' | 'right', value: string | null) {
    return <label className="project-field"><span>{side === 'left' ? 'Reference' : 'Comparison'}</span>
      <select value={value ?? ''} onChange={event => setPair(prev => ({ ...prev, [side]: event.target.value }))}>
        {completed.map(run => <option key={run.id} value={run.id}>
          {[run.label,coordinateText(run,field),run.reference ? 'Reference' : ''].filter(Boolean).join(' · ')}
        </option>)}
      </select></label>;
  }

  const error = leftDetail.error || rightDetail.error;
  const distinct = Boolean(left && right && left.id !== right.id);
  return <div className="compare-panel">
    {!fixedPair && <div className="compare-pickers">{picker('left', pair.left)}{picker('right', pair.right)}</div>}
    {pair.left && pair.left === pair.right && <Notice tone="warning">Pick two different conditions to compare.</Notice>}
    {error && <Notice tone="error">{error} <button className="project-inline-button" onClick={() => {
      if (leftDetail.error) leftDetail.retry();
      if (rightDetail.error) rightDetail.retry();
    }}>Retry loading results</button></Notice>}

    {distinct && <>
      <div className="compare-diff">
        <h5>Changed inputs</h5>
        {left?.adapter !== right?.adapter && <p>Analysis models differ: {label(left?.adapter)} and {label(right?.adapter)}.</p>}
        {changes.length === 0
          ? <p className="small muted">{bothLoaded ? 'No input differences between these conditions.' : 'Full input comparison requires both saved results.'}</p>
          : <div className="analysis-table-scroll"><table className="data-table">
              <thead><tr><th>Input</th><th>Reference</th><th>Comparison</th></tr></thead>
              <tbody>{changes.map(change => <tr key={change.key}>
                <td>{label(change.key === 'value' ? field ?? 'input' : change.key)}</td>
                <td>{coordinateValue(change.key, change.left, field, false)}</td>
                <td>{coordinateValue(change.key, change.right, field, false)}</td>
              </tr>)}</tbody>
            </table></div>}
      </div>

      <ComparePlayers key={left!.id + '|' + right!.id} leftPath={leftPath} rightPath={rightPath} fixedPair={fixedPair}
        leftDuration={recordingDuration(leftDetail.detail)} rightDuration={recordingDuration(rightDetail.detail)}/>

      <StationComparison reference={leftDetail.detail} comparison={rightDetail.detail}/>

      <div className="compare-results">
        {left ? <RunResult run={left} detail={leftDetail.detail}/> : <Loading/>}
        {right ? <RunResult run={right} detail={rightDetail.detail}/> : <Loading/>}
      </div>

    </>}
  </div>;
}
