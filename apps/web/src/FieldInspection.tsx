import { useEffect, useId, useState } from 'react';
import type { Inputs } from './analysisInputs';
import { TraceChart } from './Charts';
import { beamLoadRegions, materialReadings, measuredNumber, sectionValues, spatialField } from './recordedFields';
import './fieldInspection.css';

type Field = NonNullable<ReturnType<typeof spatialField>>;
type Material = NonNullable<ReturnType<typeof materialReadings>>;

function SampleControl({ count, index, choose, noun }: { count: number; index: number; choose: (i: number) => void; noun: string }) {
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing) return;
    if (index >= count - 1) { setPlaying(false); return; }
    const timer = window.setTimeout(() => choose(index + 1), Math.max(45, Math.min(900, 6500 / count)));
    return () => window.clearTimeout(timer);
  }, [playing, index, count, choose]);
  return <div className="inspection-controls">
    <button type="button" className="button secondary" disabled={count < 2} onClick={() => {
      if (!playing && index === count - 1) choose(0);
      setPlaying(!playing);
    }}>{playing ? 'Pause' : 'Play'} {noun === 'Station' ? 'section sweep' : 'readings'}</button>
    <label>{noun} {index + 1} of {count}<input type="range" min="0" max={count - 1} value={index} disabled={count < 2}
      aria-label={'Inspect ' + noun.toLowerCase()} onChange={event => { setPlaying(false); choose(Number(event.target.value)); }}/></label>
  </div>;
}

export function FieldDrawing({ field, node, inputs }: { field: Field; node: number; inputs: Inputs }) {
  const gradient = useId(), hatch = useId();
  const { positions, values } = field;
  const span = positions.at(-1)! - positions[0];
  const stationX = (v: number) => 44 + 552 * (v - positions[0]) / span;
  const lo = Math.min(...values), hi = Math.max(...values);
  const isBeam = field.kind === 'beam';
  const loads = isBeam ? beamLoadRegions(inputs) : [];
  const amplitude = Math.max(Math.abs(lo), Math.abs(hi));
  const scale = amplitude > 0 ? 47 / amplitude : 552 / span;
  const mag = scale / (552 / span);
  const y = (i: number) => 112 - (isBeam ? values[i] * scale : 0);
  const line = positions.map((x, i) => stationX(x) + ',' + y(i)).join(' ');
  const sx = stationX(positions[node]), sy = y(node);
  const minimum = measuredNumber(lo), maximum = measuredNumber(hi);
  return <figure className="field-inspection-figure">
    <svg viewBox="0 0 640 210" role="img" aria-label={isBeam ? 'Static beam deflection with the selected station marked' : 'Steady temperature field along the rod with the selected station marked'}>
      <defs>
        <pattern id={hatch} width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" stroke="#668493" strokeWidth="1.2"/></pattern>
        {!isBeam && <linearGradient id={gradient}>{positions.map((x, i) => {
          const t = hi === lo ? 0.5 : (values[i] - lo) / (hi - lo);
          return <stop key={i} offset={(x - positions[0]) / span} stopColor={'hsl(' + (215 - t * 198) + ' 69% 53%)'}/>;
        })}</linearGradient>}
      </defs>
      <rect width="640" height="210" fill="#f2f6f7"/>
      {isBeam ? <>
        <rect x="24" y="81" width="20" height="62" fill={'url(#' + hatch + ')'} stroke="#668493"/>
        <line x1="44" y1="112" x2="596" y2="112" stroke="#78909a" strokeDasharray="5 4"/>
        <polyline points={line} fill="none" stroke="#284c61" strokeWidth="8" strokeLinejoin="round"/>
        {typeof inputs.tip_force_n === 'number' && inputs.tip_force_n !== 0 && <text x="596" y="29" textAnchor="end">Tip force {measuredNumber(inputs.tip_force_n)} N</text>}
        {loads.map(({ start, end, force }, i) => <g key={i} stroke="#a94b23" fill="#a94b23">
          <title>{measuredNumber(force)} N applied {start === end ? 'at' : 'across'} {measuredNumber(100 * start)}%
            {start !== end && '–' + measuredNumber(100 * end) + '%'} of span</title>
          {start === end ? <circle cx={44 + 552 * start} cy="46" r="4"/> :
            <line x1={44 + 552 * start} x2={44 + 552 * end} y1="46" y2="46" strokeWidth="5"/>}
        </g>)}
        <text x="44" y="192">Fixed end</text><text x="596" y="192" textAnchor="end">Free end</text>
      </> : <>
        <rect x="44" y="96" width="552" height="32" rx="5" fill={'url(#' + gradient + ')'} stroke="#496575"/>
        <text x="44" y="49">Minimum {minimum} K</text><text x="596" y="49" textAnchor="end">Maximum {maximum} K</text>
        <text x="44" y="185">{measuredNumber(positions[0])} m</text><text x="596" y="185" textAnchor="end">{measuredNumber(positions.at(-1)!)} m</text>
      </>}
      <line x1={sx} y1={sy - 28} x2={sx} y2={sy + 28} stroke="#182f3a" strokeWidth="3"/>
      <circle cx={sx} cy={sy} r="6" stroke="#152e39" strokeWidth="2" fill="white"/>
    </svg>
    <figcaption>{isBeam ? 'Static centerline. Deflection display scale ' + measuredNumber(mag) + '× relative to the span.' :
      'Color shows the recorded steady-state temperature along the span.'} The marker moves through saved stations.
      {loads.length > 0 && <span> The orange marks show {loads.map(({ start, end, force }) =>
        measuredNumber(force) + ' N ' + (start === end ? 'at ' : 'across ') + measuredNumber(100 * start) + '%' +
        (start === end ? '' : '–' + measuredNumber(100 * end) + '%')).join(', ')} of the span from the fixed end.</span>}</figcaption>
  </figure>;
}

export function SpatialInspection({ field, inputs }: { field: Field; inputs: Inputs }) {
  const [node, setNode] = useState(0);
  return <section className="field-inspection" aria-label="Spatial field inspection">
    <h4>{field.kind === 'beam' ? 'Beam deflection by section' : 'Temperature along the rod'}</h4>
    <FieldDrawing field={field} node={node} inputs={inputs}/>
    <SampleControl count={field.positions.length} index={node} choose={setNode} noun="Station"/>
    <dl className="analysis-metrics">{sectionValues(field, node).map(metric => <div key={metric.label}><dt>{metric.label}</dt>
      <dd>{measuredNumber(metric.value)} {metric.unit}</dd></div>)}</dl>
    <details className="analysis-disclosure"><summary>Full spatial profile</summary>
      <TraceChart samples={field.positions.map((step, index) => field.kind === 'beam'
        ? { step, 'deflection (mm)': field.values[index] * 1000 }
        : { step, 'temperature (K)': field.values[index] })} xLabel="Position along span (m)"/>
    </details>
  </section>;
}

function ReadingPlot({ rows, index, unit }: { rows: Material['fit']; index: number; unit: string }) {
  const values = rows.flatMap(row => [row.measured, row.predicted]);
  const lo = Math.min(...values), hi = Math.max(...values);
  const scale = (v: number) => hi === lo ? 0.5 : (v - lo) / (hi - lo);
  const x = (v: number) => 92 + 385 * scale(v);
  const y = (v: number) => 166 - 130 * scale(v);
  const point = rows[index];
  return <figure className="field-inspection-figure">
    <svg viewBox="0 0 550 228" role="img" aria-label={'Measured and predicted readings in ' + unit + '. Selected reading ' + point.id}>
      <rect width="550" height="228" fill="#f2f6f7"/>
      <path d="M92 36V166H477" stroke="#8497a3" fill="none"/>
      <path d="M92 166L477 36" stroke="#78909a" strokeDasharray="5 4"/>
      <text x="92" y="21">Predicted {unit && '(' + unit + ')'}</text>
      {lo !== hi && <><text x="85" y="43" textAnchor="end">{measuredNumber(hi)}</text><text x="85" y="170" textAnchor="end">{measuredNumber(lo)}</text>
        <text x="92" y="188">{measuredNumber(lo)}</text><text x="477" y="188" textAnchor="end">{measuredNumber(hi)}</text></>}
      <text x="286" y="213" textAnchor="middle">Measured {unit && '(' + unit + ')'}</text>
      {rows.map(row => <circle key={row.id} cx={x(row.measured)} cy={y(row.predicted)} r="4" fill="#4d8899"><title>{row.id}</title></circle>)}
      <circle cx={x(point.measured)} cy={y(point.predicted)} r="7" fill="none" stroke="#a94116" strokeWidth="3"/>
    </svg>
    <figcaption>Each point is one independent reading. The dashed line marks agreement between prediction and measurement.</figcaption>
  </figure>;
}

export function CalibrationInspection({ data }: { data: Material }) {
  const [bank, setBank] = useState<'validation' | 'fit'>(data.validation.length ? 'validation' : 'fit');
  const [index, choose] = useState(0);
  const readings = data[bank];
  const row = readings[index];
  return <section className="field-inspection" aria-label="Material calibration inspection">
    <h4>Measured and predicted response</h4>
    <label className="project-field"><span>Measurement set</span><select value={bank}
      onChange={event => { choose(0); setBank(event.target.value as 'validation' | 'fit'); }}>
      {data.validation.length > 0 && <option value="validation">Held-out validation</option>}
      {data.fit.length > 0 && <option value="fit">Used for fitting</option>}
    </select></label>
    <ReadingPlot rows={readings} index={index} unit={data.unit}/>
    <SampleControl key={bank} count={readings.length} index={index} choose={choose} noun="Reading"/>
    <dl className="analysis-metrics"><div><dt>Measurement ID</dt><dd>{row.id}</dd></div><div><dt>Measured</dt><dd>{measuredNumber(row.measured)} {data.unit}</dd></div>
      <div><dt>Predicted</dt><dd>{measuredNumber(row.predicted)} {data.unit}</dd></div>
      {row.residual !== undefined && <div><dt>Prediction minus measurement</dt><dd>{measuredNumber(row.residual)} {data.unit}</dd></div>}
      {bank === 'validation' && data.tolerance !== undefined && <div><dt>Allowed absolute error</dt><dd>{measuredNumber(data.tolerance)} {data.unit}</dd></div>}</dl>
  </section>;
}
