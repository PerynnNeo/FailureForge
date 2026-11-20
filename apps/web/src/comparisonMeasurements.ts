import type { Inputs, RunDetail } from './analysisInputs';

type Measurement = { name: string; value: number; unit: string; maximum?: number; passed?: boolean };
type Outcome = { name: string; passed: boolean };
type Scale = [suffix: string, unit: string, factor: number];

const scales: Scale[] = [
  ['_w_m2', 'W/m²', 1], ['_m2', 'm²', 1], ['_m_s', 'm/s', 1],
  ['_rad', 'rad', 1], ['_pa', 'MPa', 1e-6], ['_m', 'mm', 1000],
  ['_k', 'K', 1], ['_kg', 'kg', 1], ['_n', 'N', 1], ['_s', 's', 1], ['_w', 'W', 1],
];

function fields(value: unknown): Inputs {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Inputs : {};
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Read each solver's saved measurements and thresholds. Verdicts always come from the run. */
export function comparisonMeasurements(run: Pick<RunDetail, 'adapter' | 'result' | 'inputs'>) {
  const result = fields(run.result);
  const summary = fields(result.summary ?? result.metrics);
  const criteria = fields(result.criteria);
  const measurements: Measurement[] = [];
  const outcomes: Outcome[] = [];

  function add(name: string, value: unknown, maximum?: unknown, unit = '', factor = 1, passed?: unknown) {
    if (finite(value)) measurements.push({ name, value: value * factor, unit,
      maximum: finite(maximum) ? maximum * factor : undefined,
      passed: typeof passed === 'boolean' ? passed : undefined });
  }
  function outcome(name: string, passed: unknown) {
    if (typeof passed === 'boolean') outcomes.push({ name, passed });
  }
  function named(key: string, value: unknown, maximum?: unknown, passed?: unknown) {
    const [suffix, unit, factor] = scales.find(([suffix]) => key.endsWith(suffix)) ?? ['', '', 1];
    const words = (suffix ? key.slice(0, -suffix.length) : key).replaceAll('_', ' ');
    add(words.charAt(0).toUpperCase() + words.slice(1), value, maximum, unit, factor, passed);
  }

  if (Array.isArray(result.acceptance_checks)) {
    for (const item of result.acceptance_checks) {
      const check = fields(item);
      if (typeof check.quantity === 'string') named(check.quantity, check.measured, check.maximum, check.passed);
    }
  }
  if (run.adapter === 'packaging_lift' || run.adapter === 'packaging_lift_timed_v2') {
    const fixture = fields(result.fixture);
    const limit = summary.error_limit_m ?? fixture.error_limit_m;
    add('Maximum hold error', summary.max_hold_error_m, limit, 'mm', 1000, criteria.held_within_tolerance);
    add('Arrival error', summary.arrival_error_m, limit, 'mm', 1000, criteria.arrived_within_tolerance);
    add('Peak speed', summary.peak_speed_m_s, fixture.speed_limit_m_s, 'm/s', 1, criteria.stayed_within_speed_limit);
    outcome('Stayed within travel limits', criteria.stayed_within_travel);
  }
  if (run.adapter === 'robot_motion') {
    const model = fields(result.model);
    const errors = fields(summary.final_absolute_joint_error);
    const speeds = fields(summary.peak_joint_speed);
    const joints = Array.isArray(model.joints) ? model.joints.map(fields) : [];
    for (const joint of joints) {
      if (typeof joint.name !== 'string' || typeof joint.unit !== 'string') continue;
      add(joint.name + ' final error', errors[joint.name], criteria.joint_target_tolerance, joint.unit);
      add(joint.name + ' peak speed', speeds[joint.name], joint.velocity_limit, joint.unit + '/s');
    }
    outcome('All joint targets reached', summary.target_reached);
    outcome('Within joint position limits', summary.within_joint_limits);
    outcome('Within joint speed limits', summary.within_velocity_limits);
  }
  if (run.adapter === 'joint_response') {
    add('Held-out joint RMSE', summary.validation_rmse_rad, run.inputs.max_validation_rmse_rad, 'rad');
  }
  if (run.adapter === 'calibration') {
    const unit = typeof summary.residual_unit === 'string' ? summary.residual_unit : '';
    add('Maximum held-out error', summary.validation_max_abs_error,
      summary.validation_tolerance ?? run.inputs.validation_tolerance, unit, 1, summary.validation_passed);
  }
  if (!measurements.length) {
    for (const [key, value] of Object.entries(summary)) named(key, value);
  }
  return { measurements, outcomes };
}
