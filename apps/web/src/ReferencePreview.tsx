import { useEffect, useState } from 'react';
import { ApiError, label, request } from './api';

type Reference = { state_id: number; seed: number; outcome: string; steps: number; cameras: { main: string; wrist: string } };

export default function ReferencePreview() {
  const [opened, setOpened] = useState(false);
  const [references, setReferences] = useState<Reference[] | null>(null);
  const [stateId, setStateId] = useState<number>();
  const [camera, setCamera] = useState<'main' | 'wrist'>('main');
  const [metadataError, setMetadataError] = useState('');
  const [mediaError, setMediaError] = useState('');
  const [src, setSrc] = useState('');
  const [token, setToken] = useState('');
  const [draftToken, setDraftToken] = useState('');
  const [needsToken, setNeedsToken] = useState(false);
  const [retry, setRetry] = useState(0);
  const selected = references?.find(item => item.state_id === stateId) ?? references?.[0];
  const url = selected?.cameras[camera];
  useEffect(() => {
    let current = true;
    setMetadataError('');
    void request<{ references: Reference[] }>('/qualification/references', token ? { headers: { Authorization: `Bearer ${token}` } } : undefined)
      .then(data => { if (current) { setReferences(data.references); setNeedsToken(false); } })
      .catch((error: Error) => { if (current) { setReferences(null); setMetadataError(error.message); setNeedsToken(error instanceof ApiError && error.status === 401); } });
    return () => { current = false; };
  }, [token, retry]);
  useEffect(() => {
    setSrc(''); setMediaError('');
    if (!opened || !url) return;
    if (!/^\/api\/qualification\/references\/\d+\/(main|wrist)$/.test(url)) { setMediaError('The reference has no supported recording URL.'); return; }
    const controller = new AbortController();
    let objectUrl = '';
    void fetch(url, { signal: controller.signal, credentials: 'same-origin', headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then(async response => {
        if (!response.ok) throw new Error(`The recording could not be loaded (HTTP ${response.status}).`);
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob); setSrc(objectUrl);
      }).catch((error: Error) => { if (!controller.signal.aborted) setMediaError(error.message); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [opened, url, token, retry]);
  function authenticate() { setToken(draftToken.trim()); setDraftToken(''); setRetry(index => index + 1); }
  return <details className="qualification-preview" onToggle={event => setOpened(event.currentTarget.open)}>
    <summary>Qualification recordings</summary>
    {metadataError ? <div role="status"><p>{metadataError}</p>{needsToken ?
      <label className="field">API token<input type="password" autoComplete="off" value={draftToken} onChange={event => setDraftToken(event.target.value)}
        onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); authenticate(); } }}/>
        <button type="button" className="button secondary" disabled={!draftToken.trim()} onClick={authenticate}>Load recordings</button></label> :
      <button type="button" className="button secondary" onClick={() => setRetry(index => index + 1)}>Retry recordings</button>}</div> :
      !references ? <p role="status">Loading qualification records…</p> :
      !selected ? <p>No reviewed qualification recordings are available.</p> : <>
        <div className="form-grid">
          <label className="field">Reference state<select aria-label="Reference state" value={selected.state_id} onChange={event => setStateId(Number(event.target.value))}>
            {references.map(item => <option key={item.state_id} value={item.state_id}>State {item.state_id} · seed {item.seed}</option>)}
          </select></label>
          <label className="field">Camera<select aria-label="Qualification camera" value={camera} onChange={event => setCamera(event.target.value as 'main' | 'wrist')}>
            <option value="main">Main</option><option value="wrist">Wrist</option>
          </select></label>
        </div>
        <p>{label(selected.outcome)} · {selected.steps} control steps</p>
        {mediaError ? <p role="status">{mediaError} <button type="button" className="project-inline-button" onClick={() => setRetry(index => index + 1)}>Retry</button></p> :
          src ? <video key={src} controls playsInline src={src} aria-label={`Reference state ${selected.state_id}, ${camera} camera`} onError={() => setMediaError('The browser could not play this recording.')}/> : <p role="status">Loading recording…</p>}
      </>}
  </details>;
}
