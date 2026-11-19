import { useState } from 'react';
import { label } from './api';
import type { Inputs, RunDetail } from './analysisInputs';
import { TraceChart } from './Charts';
import { liftHoldTrace } from './environmentConditions';
import MeshPreview from './MeshPreview';
import { MotionReplay } from './MotionReplay';
import { readMotion } from './motionData';
import { Notice } from './components';
import { CalibrationInspection, SpatialInspection } from './FieldInspection';
import { materialReadings, measuredNumber, spatialField } from './recordedFields';
import { ProjectCameraReplay } from './ProjectCameraReplay';

function LiftTrace({ result }: { result: Inputs }) {
  const [chosenQuantity, setQuantity] = useState<string | null>(null);
  const hold = liftHoldTrace(result);
  const quantity = chosenQuantity ?? (hold?.showFirst ? 'hold' : 'height');
  const series = result.series as Record<string, number[]> | undefined;
  const fixture = result.fixture as Inputs | undefined;
  if (!series || !Array.isArray(series.time_s) || !Array.isArray(series.position_m)) return null;
  const samples = quantity === 'hold' && hold ? hold.samples : series.time_s.map((time, i) => quantity === 'height'
    ? { step: time, 'lift height (mm)': 1000 * series.position_m[i],
        'target height (mm)': typeof fixture?.target_m === 'number' ? 1000 * fixture.target_m : undefined }
    : { step: time, 'motor force (N)': series.actuator_force_n?.[i], 'head force, downward (N)': series.applied_head_force_n?.[i] });
  return <section className="matrix-trace"><label className="project-field"><span>Simulated trace</span>
    <select value={quantity} onChange={event => setQuantity(event.target.value)}>
      {hold && <option value="hold">Hold error and tolerance</option>}
      <option value="height">Lift height</option><option value="force">Motor and packing head forces</option>
    </select>
  </label><TraceChart samples={samples} xLabel={quantity === 'hold' ? 'Time since hold began (s)' : 'Elapsed time (s)'}/></section>;
}

function FieldPlot({ result }: { result: Inputs }) {
  const [selectedJoint, setSelectedJoint] = useState('');
  const traces = result.traces as Inputs | undefined;
  if (result.series && result.fixture) return <LiftTrace result={result}/>;
  const trajectory = result.trajectory as Inputs | undefined;
  if (trajectory && Array.isArray(trajectory.time_s) && trajectory.joint_positions) {
    const joints = trajectory.joint_positions as Record<string, number[]>;
    const names = Object.keys(joints);
    const joint = names.includes(selectedJoint) ? selectedJoint : names[0];
    if (!joint || !Array.isArray(joints[joint])) return null;
    const model = result.model as { joints?: Array<{ name: string; unit: string }> } | undefined;
    const unit = model?.joints?.find(item => item.name === joint)?.unit ?? '';
    const series = unit ? `position (${unit})` : 'position';
    const samples = trajectory.time_s.map((step, index) => ({ step, [series]: joints[joint][index] }));
    return <section><label className="project-field"><span>Joint trajectory</span>
      <select value={joint} onChange={event => setSelectedJoint(event.target.value)}>{names.map(name => <option key={name}>{name}</option>)}</select>
    </label><TraceChart samples={samples} xLabel="Elapsed time (s)"/></section>;
  }
  const validation = traces?.validation as Record<string, number[]> | undefined;
  if (validation && Array.isArray(validation.time_s) && Array.isArray(validation.position_rad) && Array.isArray(validation.predicted_rad)) {
    const samples = validation.time_s.map((time, index) => ({
      step: time - validation.time_s[0], measured_rad: validation.position_rad[index], fitted_rad: validation.predicted_rad[index],
    }));
    return <section><h4>Held-out joint response</h4><TraceChart samples={samples} xLabel="Elapsed time (s)"/>
      {Array.isArray(validation.residual_rad) && <><h4>Held-out residual</h4>
        <TraceChart samples={validation.time_s.map((time, index) => ({ step: time - validation.time_s[0], residual_rad: validation.residual_rad[index] }))} xLabel="Elapsed time (s)"/></>}
    </section>;
  }
  return null;
}

function NumericalSummary({ result, assessmentError }: { result: Inputs; assessmentError?: string | null }) {
  const metrics = (result.summary ?? result.metrics ?? result) as Inputs;
  const scalars = Object.entries(metrics).filter(([, value]) => typeof value === 'number' && Number.isFinite(value));
  const passed = result.passed ?? metrics.passed;
  const outcome = assessmentError ? 'Inconclusive' : typeof passed === 'boolean' ? (passed ? 'Passed' : 'Failed') : null;
  const checks = Object.entries((result.criteria ?? {}) as Inputs).filter(([, value]) => typeof value === 'boolean');
  return <section className="field-inspection"><h4>Recorded result</h4>
    {outcome && <p>Recorded outcome · <strong>{outcome}</strong></p>}
    {checks.length > 0 && <ul className="matrix-checks">{checks.map(([name, passed]) => <li key={name}>{label(name)}
      <strong className={'matrix-tag ' + (passed ? 'passed' : 'failed')}>{passed ? 'Passed' : 'Failed'}</strong></li>)}</ul>}
    {scalars.length > 0 && <dl className="analysis-metrics">{scalars.map(([name, value]) => <div key={name}>
      <dt>{label(name)}</dt><dd>{measuredNumber(value as number)}</dd></div>)}</dl>}
    {!scalars.length && !outcome && !checks.length && <p className="small muted">This record contains no plottable samples. Its saved fields are available in the run details and JSON export.</p>}
  </section>;
}

function RecordedVisual({ run, result, geometryUrl }: { run: RunDetail; result: Inputs; geometryUrl?: string }) {
  const field = spatialField(result);
  if (field) return <SpatialInspection field={field} inputs={(result.inputs ?? run.inputs) as Inputs}/>;
  const data = materialReadings(result);
  if (data) return <CalibrationInspection data={data}/>;
  if (Array.isArray(result.preview_triangles_m) && result.preview_triangles_m.length) {
    const summary = result.summary as Inputs | undefined;
    return <MeshPreview triangles={result.preview_triangles_m} total={Number(summary?.triangles ?? result.preview_triangles_m.length)}/>;
  }
  if (readMotion(result)) {
    return <><MotionReplay result={result} geometryUrl={geometryUrl}/><FieldPlot result={result}/></>;
  }
  return <NumericalSummary result={result} assessmentError={run.assessment_error}/>;
}

export function RunVisual({ run, runPath }: { run: RunDetail; runPath: string }) {
  if (!run.result) return <p className="small muted">{['running', 'queued'].includes(run.status)
    ? 'The visual result will appear when the run records its evidence.'
    : 'This run has no recorded visual samples.'}</p>;
  const referenceHandExample = run.adapter === 'robot_motion' &&
    (run.result.model as Inputs | undefined)?.reference_id === 'two_finger_hand_v1' &&
    run.snapshot?.robot_template !== 'two_finger_hand_v1';
  return <>{referenceHandExample && <Notice><strong>Reference hand example.</strong> This run used the built-in two-finger hand. Its motion and outcome apply to that model.</Notice>}
    <ProjectCameraReplay key={runPath} runPath={runPath}>
      <RecordedVisual run={run} result={run.result} geometryUrl={run.adapter === 'robot_motion' ? `/api${runPath}/replay-geometry` : undefined}/>
    </ProjectCameraReplay>
  </>;
}
