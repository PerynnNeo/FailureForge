import { useEffect, useRef, useState, type FormEvent } from 'react';
import { label, post, request } from './api';
import { Loading, Notice } from './components';

type Observable = {id: string; label: string; prediction: number; unit: string; units: string[];
  station_m: number | null; station_reference: string; nonnegative: boolean};
type Prediction = {id: string; prototype_id: string; setup: string; observable: Observable;
  frozen_at: string; settings: Record<string, number>; setting_units?: Record<string, string>; assumptions: string[];
  fixture?: Record<string, unknown> | null; model_inputs: Record<string, unknown>};
type Measurement = {id: string; prototype_id: string; trial_id: string; source: string; condition_record: string;
  conclusion: string; reasons: string[]; measured: number; interval: number[] | null; residual: number;
  unit: string; uncertainty_basis: string; source_kind: string; recorded_at: string};
type Catalog = {observables: Observable[]; predictions: Prediction[]};
type Report = {prediction: Prediction; measurements: Measurement[]};
type Asset = {id: string; filename: string};
const fmt = (value: number) => Number(value.toPrecision(7)).toString();
const stations = {free_end: 'At the free end', from_origin: 'Distance from the clamp or rod origin',
  whole_fixture: 'Whole fixture or specified joint', unknown: 'Unknown or different station'};

function useSubmissionKey() {
  const last = useRef({body: '', key: ''});
  return (body: unknown) => {
    const encoded = JSON.stringify(body);
    if (last.current.body !== encoded) last.current = {body: encoded, key: crypto.randomUUID()};
    return last.current.key;
  };
}

function MeasurementForm({path, prediction, assets, onSave}: {
  path: string; prediction: Prediction; assets: Asset[]; onSave: (measurement: Measurement) => void;
}) {
  const observable = prediction.observable;
  const [sourceKind, setSourceKind] = useState('published');
  const [station, setStation] = useState('unknown');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submissionKey = useSubmissionKey();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const field = (name: string) => String(data.get(name) ?? '').trim();
    const actual: Record<string, number> = {};
    for (const key of Object.keys(prediction.settings)) {
      if (field('setting-' + key)) actual[key] = Number(field('setting-' + key));
    }
    const body = {prototype_id: field('specimen'), trial_id: field('trial'), source: field('source'),
      asset_id: field('asset') || null, condition_record: field('conditions'), source_kind: sourceKind,
      measured_at: field('acquired') ? new Date(field('acquired')).toISOString() : null,
      independent: data.has('independent'), fixture_matches: data.has('fixture'), actual_settings: actual,
      station_reference: station, station_m: station === 'from_origin' ? Number(field('station')) : null,
      value: Number(field('reading')), unit: field('unit'),
      uncertainty: field('uncertainty') ? Number(field('uncertainty')) : null, uncertainty_basis: field('basis')};
    setBusy(true); setError('');
    try {
      const saved = await post<Measurement>(path + '/measurements', body, submissionKey(body));
      onSave(saved); form.reset(); setStation('unknown'); setSourceKind('published');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not record the physical measurement.'); }
    finally { setBusy(false); }
  }

  return <details><summary>Record a physical measurement</summary>
    <form onSubmit={submit} className="project-form-stack">
      <p>Transcribe the physical setup and reading from the test record. Missing settings and unknown uncertainty leave the comparison indeterminate.</p>
      <label className="project-field"><span>Evidence timing</span><select value={sourceKind} onChange={e => setSourceKind(e.target.value)}>
        <option value="published">Existing measurement or published experiment</option>
        <option value="new_trial">New trial acquired after this freeze</option></select></label>
      {sourceKind === 'new_trial' && <label className="project-field"><span>Acquisition time (local time)</span>
        <input name="acquired" type="datetime-local" step="1" required/></label>}
      <label className="project-field"><span>Specimen ID in the physical record</span><input name="specimen" required maxLength={160}/></label>
      <label className="project-field"><span>Physical trial ID</span><input name="trial" required maxLength={160}/></label>
      <label className="project-field"><span>Source and exact reading location</span>
        <textarea name="source" required maxLength={3000} placeholder="Report identifier, table and row, or instrument log and channel"/></label>
      {assets.length > 0 && <label className="project-field"><span>Attach a project measurement file (optional)</span>
        <select name="asset"><option value="">No attachment</option>{assets.map(a =>
          <option key={a.id} value={a.id}>{a.filename}</option>)}</select></label>}
      <label className="project-field"><span>Physical setup and measurement method</span>
        <textarea name="conditions" required maxLength={3000} placeholder="Describe the fixture, direction, operating conditions and how the reading was taken."/></label>
      <label className="project-field"><span>Physical measurement station</span><select value={station} onChange={e => setStation(e.target.value)}>
        {Object.entries(stations).map(([key, name]) => <option value={key} key={key}>{name}</option>)}</select></label>
      {station === 'from_origin' && <label className="project-field"><span>Measured station from origin (m)</span>
        <input name="station" type="number" step="any" min="0" required/></label>}
      {Object.entries(prediction.settings).map(([key, value]) => <label className="project-field" key={key}>
        <span>Physical {label(key)} · model {fmt(value)} {prediction.setting_units?.[key]}</span>
        <input name={'setting-' + key} type="number" step="any" placeholder="Leave blank if unknown"/></label>)}
      <label className="project-field"><span>Measured {observable.label}</span>
        <input name="reading" type="number" step="any" min={observable.nonnegative && observable.unit !== 'K' ? 0 : undefined} required/></label>
      <label className="project-field"><span>Reading and uncertainty unit</span><select name="unit">
        {observable.units.map(unit => <option key={unit}>{unit}</option>)}</select></label>
      <label className="project-field"><span>Absolute measurement uncertainty (±)</span>
        <input name="uncertainty" type="number" step="any" min="0" placeholder="Leave blank if unreported"/></label>
      <label className="project-field"><span>Uncertainty basis</span>
        <textarea name="basis" required maxLength={3000} placeholder="Record the source’s coverage, method and included effects, or explain what is unknown."/></label>
      <label><input name="fixture" type="checkbox"/> The physical fixture, directions and quantity match the frozen test definition.</label>
      <label><input name="independent" type="checkbox"/> This measurement was acquired independently and was unused in fitting this prediction.</label>
      <button className="button primary" disabled={busy}>{busy ? 'Recording…' : 'Record measurement and compare'}</button>
      {error && <Notice tone="error">{error}</Notice>}
    </form>
  </details>;
}

function TrialReport({path, assets}: {path: string; assets: Asset[]}) {
  const [report, setReport] = useState<Report>();
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let current = true;
    setError('');
    request<Report>(path).then(data => { if (current) setReport(data); }, e => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [path, retry]);
  if (error) return <Notice tone="error">{error} <button type="button" onClick={() => setRetry(n => n + 1)}>Retry</button></Notice>;
  if (!report) return <Loading/>;
  const {prediction, measurements} = report;
  const {observable} = prediction;
  return <section className="project-form-stack" aria-label="Frozen physical trial">
    <h4>{observable.label} · {fmt(observable.prediction)} {observable.unit}</h4>
    <p>{prediction.prototype_id} · frozen {new Date(prediction.frozen_at).toLocaleString()}</p>
    <p>{prediction.setup}</p>
    <details><summary>Frozen model inputs and assumptions</summary>
      <pre>{JSON.stringify(prediction.model_inputs, null, 2)}</pre>
      {prediction.fixture && <pre>{JSON.stringify(prediction.fixture, null, 2)}</pre>}
      {prediction.assumptions.map((a, i) => <p key={i}>{a}</p>)}</details>
    {measurements.map(item => <article className="project-form-stack" key={item.id}>
      <h4>{item.trial_id} · {label(item.conclusion)}</h4>
      <p>{item.source_kind === 'published' ? 'Existing physical evidence' : 'Trial acquired after freeze'} · {item.prototype_id}</p>
      <p>Predicted <strong>{fmt(observable.prediction)} {item.unit}</strong> · measured <strong>{fmt(item.measured)} {item.unit}</strong> · measured minus predicted <strong>{fmt(item.residual)} {item.unit}</strong></p>
      <p>{item.interval ? 'Reported measurement interval ' + item.interval.map(fmt).join(' to ') + ' ' + item.unit : 'Measurement interval unavailable'}. {item.uncertainty_basis}</p>
      {item.reasons.length ? <ul>{item.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul> :
        <p>The deterministic prediction is {item.conclusion === 'agrees' ? 'inside' : 'outside'} the stated physical measurement interval.</p>}
      <p>{item.source}</p><details><summary>Physical setup</summary><p>{item.condition_record}</p></details>
    </article>)}
    <MeasurementForm path={path} prediction={prediction} assets={assets} onSave={reading =>
      setReport(current => current && ({...current, measurements: [...current.measurements.filter(m => m.id !== reading.id), reading]}))}/>
    <a className="text-link" href={'/api' + path} download="frozen-physical-trial.json">Download frozen prediction and measurement records</a>
  </section>;
}

export function FrozenTrialCheck({path, assets}: {path: string; assets: Asset[]}) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [selected, setSelected] = useState('');
  const [choice, setChoice] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const submissionKey = useSubmissionKey();
  useEffect(() => {
    let current = true;
    setError('');
    request<Catalog>(path).then(data => {
      if (current) { setCatalog(data); setSelected(data.predictions[0]?.id ?? ''); setChoice(data.observables[0]?.id ?? ''); }
    }, e => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [path, retry]);

  async function freeze(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const body = {observable_id: choice, prototype_id: fields.get('specimen'), setup: fields.get('setup')};
    setError(''); setBusy(true);
    try {
      const saved = await post<Prediction>(path, body, submissionKey(body));
      setCatalog(current => current && ({...current, predictions: [saved, ...current.predictions.filter(p => p.id !== saved.id)]}));
      setSelected(saved.id); form.reset();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not freeze this prediction.'); }
    finally { setBusy(false); }
  }
  const observable = catalog?.observables.find(item => item.id === choice);
  return <div className="project-form-stack">
    {error && <Notice tone="error">{error} {!catalog && <button type="button" onClick={() => setRetry(n => n + 1)}>Retry</button>}</Notice>}
    {!catalog && !error && <Loading/>}
    {catalog && (catalog.observables.length ? <>
      <details open={!catalog.predictions.length || undefined}><summary>Freeze a prediction</summary>
        <form className="project-form-stack" onSubmit={freeze}>
          <p>Choose the quantity your instrument measures. Save the specimen and model assumptions before entering the physical reading.</p>
          <label className="project-field"><span>Predicted quantity and station</span><select value={choice} onChange={e => setChoice(e.target.value)}>
            {catalog.observables.map(item => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
          {observable && <p>Simulation predicts <strong>{fmt(observable.prediction)} {observable.unit}</strong>.</p>}
          <label className="project-field"><span>Prototype or specimen ID</span><input name="specimen" required maxLength={160}/></label>
          <label className="project-field"><span>Test definition and assumptions</span><textarea name="setup" required maxLength={3000}
            placeholder="Identify the source of the geometry, material, fixture, direction and measurement definition."/></label>
          <button className="button primary" disabled={busy}>{busy ? 'Freezing…' : 'Freeze prediction'}</button>
        </form></details>
      {catalog.predictions.length > 0 && <label className="project-field"><span>Saved prediction</span>
        <select value={selected} onChange={e => setSelected(e.target.value)}>{catalog.predictions.map(item =>
          <option value={item.id} key={item.id}>{item.prototype_id} · {item.observable.label} · {new Date(item.frozen_at).toLocaleString()}</option>)}</select></label>}
      {selected && <TrialReport key={selected} path={path + '/' + encodeURIComponent(selected)} assets={assets}/>}
    </> : <p>No supported physical observable was recorded on this run.</p>)}
  </div>;
}
