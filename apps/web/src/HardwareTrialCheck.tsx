import { useEffect, useState } from 'react';
import { label, request } from './api';
import type { RunDetail } from './analysisInputs';
import { Loading, Notice } from './components';

type Catalog = {metrics: Record<string,unknown>; assets: {id: string; filename: string}[]};
type Report = {asset_sha256: string; rows: {metric: string; unit: string; prototype_id: string; trial_id: string;
  condition_record: string; measured: number; uncertainty: number; residual: number; prediction: number;
  maximum: number; physical_verdict: string; simulation_verdict: string; agreement: string; differing_settings: string[]}[]};
const fmt = (value: number) => Number(value.toPrecision(6)).toString();

export function HardwareTrialCheck({projectId, run}: {projectId: string; run: RunDetail}) {
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<Catalog>();
  const [asset, setAsset] = useState('');
  const [report, setReport] = useState<Report>();
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const path = '/projects/' + encodeURIComponent(projectId) + '/analysis/' + encodeURIComponent(run.id) + '/hardware-trials';
  useEffect(() => {
    if (!open) return;
    let current = true;
    setError(''); setReport(undefined);
    if (asset) {
      request<Report>(path + '/' + encodeURIComponent(asset)).then(data => { if (current) setReport(data); },
        e => { if (current) setError(e.message); });
    } else {
      request<Catalog>(path).then(data => { if (current) setCatalog(data); }, e => { if (current) setError(e.message); });
    }
    return () => {current = false;};
  }, [open, path, asset, retry]);
  if (run.status !== 'completed' || run.assessment_error || !run.evidence_hash) return null;
  return <details onToggle={e => setOpen(e.currentTarget.open)}><summary>Check against a physical trial</summary>
    {open && <div className="project-form-stack">
      {error && <Notice tone="error">{error} <button type="button" className="project-inline-button" onClick={() => setRetry(n => n + 1)}>Retry</button></Notice>}
      {!error && !catalog && <Loading/>}
      {catalog && (Object.keys(catalog.metrics).length ? <>
        <p>Use one row per trial and metric. Keep the simulated settings from the template. In trial_settings_json, enter the settings documented on the physical rig using the same keys and units. Enter its ID, trial ID, setup record, measurement and absolute uncertainty. Remove unused rows.</p>
        <a className="text-link" download href={'/api' + path + '/template.csv'}>Download this run’s trial template</a>
        <p>Upload the completed CSV in <a className="text-link" href={'#/projects/' + encodeURIComponent(projectId) + '?tab=files'}>project Files</a> as Physical measurements, then select it here.</p>
        {catalog.assets.length > 0 ? <label className="project-field"><span>Hardware measurement file</span>
          <select value={asset} onChange={e => setAsset(e.target.value)}><option value="">Select an uploaded CSV</option>
            {catalog.assets.map(a => <option key={a.id} value={a.id}>{a.filename}</option>)}</select></label> : <p>No physical measurement CSVs attached.</p>}
        {asset && !report && !error && <Loading/>}
        {report && <><div className="analysis-table-scroll"><table className="data-table"><thead><tr>
          <th>Trial and metric</th><th>Predicted</th><th>Measured ± uncertainty</th><th>Maximum</th><th>Measured − predicted</th><th>Limit verdicts</th>
        </tr></thead><tbody>{report.rows.map(row => <tr key={JSON.stringify([row.prototype_id,row.trial_id,row.metric])}>
          <td>{row.prototype_id} · {row.trial_id}<small>{label(row.metric)} ({row.unit})</small><small>{row.condition_record}</small></td>
          <td>{fmt(row.prediction)}</td><td>{fmt(row.measured)} ± {fmt(row.uncertainty)}</td><td>{fmt(row.maximum)}</td>
          <td>{fmt(row.residual)}</td><td>{row.agreement}<small>Simulated {row.simulation_verdict} · measured {row.physical_verdict}</small>
            {row.differing_settings.length > 0 && <small>Check {row.differing_settings.map(label).join(', ')}</small>}</td>
        </tr>)}</tbody></table></div><a className="text-link" href={'/api' + path + '/' + encodeURIComponent(asset)} download="hardware-comparison.json">Download comparison and evidence hashes</a></>}
      </> : <p>This run has no supported numeric acceptance limit for a direct hardware comparison.</p>)}
    </div>}
  </details>;
}
