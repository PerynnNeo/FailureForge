import { useEffect, useRef, useState } from 'react';
import type { ReactNode, RefObject } from 'react';
import { post, request } from './api';
import { Icon } from './components';
import { synchronizeCameras } from './cameraPlayback';
import './projectCameraReplay.css';

export type View = { id: 'main' | 'detail'; label: string; url: string };
export type Replay = {
  status: 'ready' | 'available' | 'rendering' | 'unavailable' | 'failed';
  description: string; views?: View[]; duration_s?: number;
};

const inFlight = new Map<string, Promise<Replay>>();
function replayRequest(path: string, render = false) {
  const key = (render ? 'POST ' : 'GET ') + path;
  const existing = inFlight.get(key);
  if (existing) return existing;
  const pending = (render ? post<Replay>(path, {}) : request<Replay>(path)).finally(() => inFlight.delete(key));
  inFlight.set(key, pending);
  return pending;
}

function CameraPair({ main, detail }: { main: View; detail: View }) {
  const first = useRef<HTMLVideoElement>(null), second = useRef<HTMLVideoElement>(null);
  const playback = useRef<ReturnType<typeof synchronizeCameras> | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!first.current || !second.current) return;
    const sync = synchronizeCameras(first.current, second.current, () => setError('The browser could not play both camera views.'));
    playback.current = sync;
    return () => { sync.disconnect(); playback.current = null; };
  }, [main.url, detail.url, attempt]);
  function failed(view: View) {
    first.current?.pause(); second.current?.pause();
    setError(`The ${view.label} video could not be loaded.`);
  }
  return <>
    <div className="project-camera-pair">{[main, detail].map((view, index) =>
      <figure key={view.id}><figcaption>{view.label}</figcaption>
        <video key={view.url + attempt} ref={index ? second : first} src={view.url} aria-label={view.label + ' camera replay'}
          controls playsInline muted preload="auto" onError={() => failed(view)}/>
      </figure>)}</div>
    <div className="project-camera-actions"><span>Playback is synchronized across both views.</span>
      <button className="project-inline-button" type="button" disabled={Boolean(error)} onClick={() => playback.current?.restart()}><Icon name="refresh" size={14}/>Restart both views</button>
    </div>
    {error && <p role="alert">{error} <button type="button" className="project-inline-button" onClick={() => { setError(''); setAttempt(n => n + 1); }}>Retry playback</button></p>}
  </>;
}

export type CameraReplayState = { replay: Replay | null; requestError: string; retry: () => void };

/** Load a run's camera replay (available -> POST render -> ready polling), gated on `active`. */
export function useCameraReplay(path: string, active: boolean): CameraReplayState {
  const retryFailed = useRef(false);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [requestError, setRequestError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!active) return;
    let current = true, timer = 0, submitted = false;
    async function load() {
      try {
        let result = await replayRequest(path);
        if (!current) return;
        if (!submitted && (result.status === 'available' || (result.status === 'failed' && retryFailed.current))) {
          submitted = true; retryFailed.current = false;
          setReplay({ ...result, status: 'rendering', description: 'Preparing the two camera views from this run.' });
          result = await replayRequest(path, true);
        }
        if (!current) return;
        retryFailed.current = false;
        if (result.status === 'available' && submitted) throw new Error('The camera render has not started.');
        if (result.status === 'ready' && !['main', 'detail'].every(id =>
          result.views?.some(view => view.id === id && view.label && view.url === `/api${path}/${id}.mp4`))) {
          throw new Error('The camera replay is missing a video file.');
        }
        setReplay(result); setRequestError('');
        if (result.status === 'rendering') timer = window.setTimeout(() => void load(), 1800);
      } catch (failure) { if (current) setRequestError((failure as Error).message); }
    }
    void load();
    return () => { current = false; window.clearTimeout(timer); };
  }, [path, active, attempt]);
  function retry() { retryFailed.current = true; setRequestError(''); setReplay(null); setAttempt(n => n + 1); }
  return { replay, requestError, retry };
}

/**
 * True only while `ref`'s element is intersecting the viewport and the tab is visible. Used to
 * gate camera-replay rendering/polling so it does not fire when the panel is off-screen or hidden.
 */
export function useViewportActive(ref: RefObject<HTMLElement | null>): boolean {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    let intersecting = false;
    const update = () => setVisible(intersecting && !document.hidden);
    const observer = new IntersectionObserver(([entry]) => { intersecting = entry.isIntersecting; update(); });
    observer.observe(ref.current);
    document.addEventListener('visibilitychange', update);
    return () => { observer.disconnect(); document.removeEventListener('visibilitychange', update); };
  }, [ref]);
  return visible;
}

export function ProjectCameraReplay({ runPath, children }: { runPath: string; children: ReactNode }) {
  const path = runPath + '/camera-replay';
  const container = useRef<HTMLElement>(null);
  const visible = useViewportActive(container);
  const [inspect, setInspect] = useState(false);

  const { replay, requestError, retry } = useCameraReplay(path, visible);
  const unavailable = replay?.status === 'unavailable';
  const failed = Boolean(requestError) || replay?.status === 'failed';
  const ready = replay?.status === 'ready' && !requestError;
  const main = replay?.views?.find(view => view.id === 'main'), detail = replay?.views?.find(view => view.id === 'detail');
  return <>
    <section ref={container} className="project-camera-replay" aria-label="Camera replay">
      <h4>{ready ? 'Reconstructed camera replay' : 'Camera replay'}</h4>
      <p className="project-camera-status" role="status">{requestError || replay?.description || 'Checking camera views for this run…'}</p>
      {failed && <button type="button" className="project-inline-button" onClick={retry}>Retry camera replay</button>}
      {ready && main && detail && <CameraPair main={main} detail={detail}/>}
    </section>
    {unavailable || failed ? children : <details className="analysis-disclosure project-camera-details"
      onToggle={event => setInspect(event.currentTarget.open)}>
      <summary>Inspect the model and recorded values</summary>{inspect && children}
    </details>}
  </>;
}
