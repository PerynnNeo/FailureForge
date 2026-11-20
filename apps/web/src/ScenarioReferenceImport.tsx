import { useRef, useState } from 'react';
import type { Project } from './projectTypes';
import { post, request } from './api';
import { Notice } from './components';

export function ScenarioReferenceImport({ project, disabled, onSaved, onRun }: {
  project: Project; disabled: boolean; onSaved: (project: Project) => void; onRun: (id: string) => void;
}) {
  const [assetId, setAssetId] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const assets = project.assets.filter(asset => asset.kind === 'requirements' && asset.filename.toLowerCase().endsWith('.json') && asset.size_bytes <= 65536);
  const base = `/projects/${encodeURIComponent(project.id)}`;
  const isBeam = project.analysis_type === 'structural';
  if (!isBeam && project.robot_template !== 'packaging_lift_v1') return null;

  async function submit() {
    setError(''); setBusy(true);
    try {
      let selected = assetId;
      let revision = project.revision;
      if (!selected && file) {
        if (file.size > 65536 || !file.name.toLowerCase().endsWith('.json')) throw new Error('Choose a JSON definition up to 64 KiB.');
        const updated = await request<Project>(`${base}/assets?kind=requirements&filename=${encodeURIComponent(file.name)}`, {
          method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' },
        });
        onSaved(updated);
        const uploaded = updated.assets.filter(asset => asset.kind === 'requirements' && asset.filename === file.name
          && !project.assets.some(previous => previous.id === asset.id));
        setFile(null);
        if (fileInput.current) fileInput.current.value = '';
        if (uploaded.length !== 1) throw new Error('Select the saved JSON file to use as the reference.');
        selected = uploaded[0].id;
        revision = updated.revision;
        setAssetId(selected);
      }
      const body = { expected_revision: revision, asset_id: selected };
      const receipt = await post<{ ids: string[] }>(`${base}/scenarios/import-reference`, body, `reference-${revision}-${selected}`);
      onRun(receipt.ids[0]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'The reference could not be imported.'); }
    finally { setBusy(false); }
  }

  return <details className="scenario-import"><summary>Import a reference model from JSON</summary>
    <p>Choose a JSON file up to 64 KiB containing the solver’s <code>adapter</code> and <code>inputs</code>. Importing saves the file and runs its reference case on the CPU.</p>
    {isBeam && <a className="text-link" download href="/examples/beam-reference.json">Download example beam JSON</a>}
    <fieldset disabled={disabled || busy} className="scenario-import-fields">
      {assets.length > 0 && <label className="project-field"><span>Saved JSON file</span>
        <select value={assetId} onChange={event => setAssetId(event.target.value)}>
          <option value="">Upload a new file</option>{assets.map(asset => <option key={asset.id} value={asset.id}>{asset.filename} · {asset.id.slice(-6)}</option>)}
        </select></label>}
      {!assetId && <label className="project-field"><span>Reference JSON file</span>
        <input type="file" ref={fileInput} accept=".json,application/json" onChange={event => setFile(event.target.files?.[0] ?? null)}/></label>}
      <button type="button" className="button secondary" disabled={!file && !assetId} onClick={() => void submit()}>
        {busy ? 'Importing reference…' : 'Import and run reference'}</button>
    </fieldset>
    {error && <Notice tone="error">{error}</Notice>}
  </details>;
}
