import { useState } from 'react';
import type { Inputs, RunDetail } from './analysisInputs';
import { FieldDrawing } from './FieldInspection';
import { measuredNumber, spatialField } from './recordedFields';

type Field = NonNullable<ReturnType<typeof spatialField>>;

function Gauge({ side, field, inputs, index, select }: {
  side: string; field: Field; inputs: Inputs; index: number; select: (index: number) => void;
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
    <FieldDrawing field={field} node={index} inputs={inputs}/>
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

function StationPair({ left, right, leftInputs, rightInputs }: { left: Field; right: Field; leftInputs: Inputs; rightInputs: Inputs }) {
  const [reference, setReference] = useState(left.positions.length - 1);
  const [comparison, setComparison] = useState(right.positions.length - 1);
  const beam = left.kind === 'beam';
  const scale = beam ? 1000 : 1;
  const a = left.values[reference] * scale, b = right.values[comparison] * scale;
  return <section className="field-inspection station-comparison" aria-label="Compare measurement stations">
    <h4>Compare measurement stations</h4>
    <p>Choose a recorded position on each run, measured from the {beam ? 'clamp' : 'left end'}.</p>
    <div className="project-form-grid">
      <Gauge side="Reference" field={left} inputs={leftInputs} index={reference} select={setReference}/>
      <Gauge side="Comparison" field={right} inputs={rightInputs} index={comparison} select={setComparison}/>
    </div>
    <p>{measuredNumber(a) === measuredNumber(b) ? 'The simulated readings agree to the displayed precision.' :
      <>Simulated difference (comparison minus reference) <strong>{measuredNumber(b - a)} {beam ? 'mm' : 'K'}</strong></>}</p>
  </section>;
}

export function StationComparison({ reference, comparison }: { reference?: RunDetail | null; comparison?: RunDetail | null }) {
  if (!reference?.result || !comparison?.result || reference.id === comparison.id ||
      [reference, comparison].some(run => run.status !== 'completed' || run.error || run.assessment_error)) return null;
  const left = spatialField(reference.result), right = spatialField(comparison.result);
  if (!left || !right || left.kind !== right.kind) return null;
  return <StationPair key={reference.id + '/' + comparison.id} left={left} right={right}
    leftInputs={reference.inputs} rightInputs={comparison.inputs}/>;
}
