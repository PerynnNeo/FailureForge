import { useState } from 'react';
import type { Inputs, RunDetail } from './analysisInputs';
import { FieldDrawing } from './FieldInspection';
import { fieldDomain, measuredNumber, object, spatialField } from './recordedFields';
import { stationHref, type StationPairLink } from './stationLink';

type Field = NonNullable<ReturnType<typeof spatialField>>;

function Gauge({ side, field, inputs, index, select, domain, sharedGain }: {
  side: string; field: Field; inputs: Inputs; index: number; select: (index: number) => void;
  domain: [number, number]; sharedGain?: number;
}) {
  const beam = field.kind === 'beam';
  const unit = beam ? 'mm' : 'K';
  const simulated = field.values[index] * (beam ? 1000 : 1);
  const [readings, setReadings] = useState<Record<number, string>>({});
  const reading = readings[index] || '';
  return <div className="station-reading"><label className="project-field"><span>{side} station</span>
    <select aria-label={side + ' station'} value={index} onChange={event => select(Number(event.target.value))}>
      {field.positions.map((position, i) => <option value={i} key={i}>{measuredNumber(1000 * position)} mm</option>)}
    </select>
  </label>
    <FieldDrawing field={field} node={index} inputs={inputs} domain={domain} sharedGain={sharedGain}/>
    <p>Simulated {beam ? 'deflection' : 'temperature'} <strong>{measuredNumber(simulated)} {unit}</strong></p>
    <details><summary>Compare a bench reading</summary>
      <label className="project-field"><span>{side} bench reading ({unit})</span>
        <input type="number" step="any" aria-label={side + ' bench reading (' + unit + ')'} value={reading}
          onChange={event => setReadings({ ...readings, [index]: event.target.value })}/>
        <small>Optional reading at this station, kept in this view.</small>
      </label>
      {reading.trim() && Number.isFinite(Number(reading)) && <p>Simulation minus bench <strong>{measuredNumber(simulated - Number(reading))} {unit}</strong></p>}
    </details>
  </div>;
}

function StationPair({ left, right, leftInputs, rightInputs, link, batchHref, referenceId }: {
  left: Field; right: Field; leftInputs: Inputs; rightInputs: Inputs; link?: StationPairLink;
  batchHref?: string; referenceId: string;
}) {
  const linkedLeft = link ? left.positions.indexOf(link.leftM) : -1;
  const linkedRight = link ? right.positions.indexOf(link.rightM) : -1;
  const available = linkedLeft >= 0 && linkedRight >= 0;
  const [reference, setReference] = useState(available ? linkedLeft : left.positions.length - 1);
  const [comparison, setComparison] = useState(available ? linkedRight : right.positions.length - 1);
  const beam = left.kind === 'beam';
  const scale = beam ? 1000 : 1;
  const a = left.values[reference] * scale, b = right.values[comparison] * scale;
  const limits = beam ? [] : [leftInputs.max_temperature_k, rightInputs.max_temperature_k];
  const domain = fieldDomain([left, right], limits);
  const peak = Math.max(...domain.map(Math.abs));
  const span = Math.min(...[left, right].map(f => f.positions.at(-1)! - f.positions[0]));
  const sharedGain = beam ? (peak ? Math.max(1, Math.min(10000, .075 * span / peak)) : 1) : undefined;
  return <section className="field-inspection station-comparison" aria-label="Compare measurement stations">
    <h4>Compare measurement stations</h4>
    <p>{beam ? 'Where was the dial gauge or displacement sensor for each load case? Choose each station from the clamp.' :
      'Where was the temperature sensor for each case? Choose each station from the left end.'}</p>
    {link && !available && <p role="alert">The linked stations could not be found in these recordings. Select both positions below.</p>}
    <div className="project-form-grid">
      <Gauge side="Reference" field={left} inputs={leftInputs} index={reference} select={setReference} domain={domain} sharedGain={sharedGain}/>
      <Gauge side="Comparison" field={right} inputs={rightInputs} index={comparison} select={setComparison} domain={domain} sharedGain={sharedGain}/>
    </div>
    <p>{measuredNumber(a) === measuredNumber(b) ? 'The simulated readings agree to the displayed precision.' :
      <>Simulated difference (comparison minus reference) <strong>{measuredNumber(b - a)} {beam ? 'mm' : 'K'}</strong></>}</p>
    {batchHref && <a className="text-link" href={stationHref(batchHref, referenceId, left.positions[reference], right.positions[comparison])}>
      Open replay at these measurement stations</a>}
  </section>;
}

export function StationComparison({ reference, comparison, batchHref, link }: {
  reference?: RunDetail | null; comparison?: RunDetail | null; batchHref?: string; link?: StationPairLink;
}) {
  if (!reference?.result || !comparison?.result || reference.id === comparison.id ||
      [reference, comparison].some(run => run.status !== 'completed' || run.error || run.assessment_error)) return null;
  const left = spatialField(reference.result), right = spatialField(comparison.result);
  if (!left || !right || left.kind !== right.kind) return null;
  const activeLink = link?.reference === reference.id && link.comparison === comparison.id ? link : undefined;
  return <StationPair key={[reference.id, comparison.id, activeLink?.leftM, activeLink?.rightM].join('/')}
    referenceId={reference.id} batchHref={batchHref} link={activeLink} left={left} right={right}
    leftInputs={object(reference.result.inputs ?? reference.inputs)} rightInputs={object(comparison.result.inputs ?? comparison.inputs)}/>;
}
