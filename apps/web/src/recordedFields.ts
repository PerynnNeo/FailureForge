import type { Inputs } from './analysisInputs';

function object(value: unknown): Inputs {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Inputs : {};
}

function numericArray(value: unknown, length?: number): number[] | undefined {
  if (!Array.isArray(value) || !value.length || !value.every(Number.isFinite)) return undefined;
  return length === undefined || value.length === length ? value : undefined;
}

/** Positions are fractions of the span measured outward from the clamp. */
export function beamLoadRegions(inputs: Inputs) {
  if (!Array.isArray(inputs.span_loads)) return [];
  return inputs.span_loads.flatMap(value => {
    const { start_fraction: start, end_fraction: end, force_n: force } = object(value);
    if (typeof start !== 'number' || typeof end !== 'number' || typeof force !== 'number' ||
        ![start, end, force].every(Number.isFinite) || start < 0 || end > 1 || end < start || force === 0) return [];
    return [{ start, end, force }];
  });
}

type SpatialField = {
  kind: 'beam' | 'rod'; positions: number[]; values: number[];
  rotation?: number[]; stressLeft?: number[]; stressRight?: number[]; flux?: number[];
};

export function spatialField(result: Inputs): SpatialField | null {
  const traces = object(result.traces);
  const positions = numericArray(traces.node_position_m);
  if (!positions || positions.length < 2 || positions.some((x, i) => i > 0 && x <= positions[i - 1])) return null;
  const nodes = positions.length;
  if (result.kind === 'structural_beam') {
    const values = numericArray(traces.displacement_m, nodes);
    return values ? { kind: 'beam', positions, values, rotation: numericArray(traces.rotation_rad, nodes),
      stressLeft: numericArray(traces.element_left_surface_stress_pa, nodes - 1),
      stressRight: numericArray(traces.element_right_surface_stress_pa, nodes - 1) } : null;
  }
  if (result.kind === 'thermal_rod') {
    const values = numericArray(traces.temperature_k, nodes);
    return values ? { kind: 'rod', positions, values, flux: numericArray(traces.element_heat_flux_w_m2, nodes - 1) } : null;
  }
  return null;
}

type Reading = { id: string; measured: number; predicted: number; residual?: number };
function readings(value: unknown): Reading[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap(row => {
    const { run_id, measured, predicted, residual } = object(row);
    if (typeof run_id !== 'string' || typeof measured !== 'number' || !Number.isFinite(measured) ||
      typeof predicted !== 'number' || !Number.isFinite(predicted)) return [];
    return [{ id: run_id, measured, predicted, residual: typeof residual === 'number' && Number.isFinite(residual) ? residual : undefined }];
  });
}

export function materialReadings(result: Inputs) {
  if (result.kind !== 'calibration') return null;
  const { residual_unit, validation_tolerance } = object(result.summary);
  const fit = readings(result.fit), validation = readings(result.validation);
  if (!fit.length && !validation.length) return null;
  return { fit, validation, unit: typeof residual_unit === 'string' ? residual_unit : '',
    tolerance: typeof validation_tolerance === 'number' && Number.isFinite(validation_tolerance) ? validation_tolerance : undefined };
}

export function sectionValues(field: SpatialField, node: number) {
  const values = [{ label: 'Station', value: field.positions[node], unit: 'm' }];
  if (field.kind === 'beam') {
    values.push({ label: 'Deflection', value: field.values[node] * 1000, unit: 'mm' });
    if (field.rotation) values.push({ label: 'Rotation', value: field.rotation[node], unit: 'rad' });
    if (node > 0 && field.stressRight) values.push({ label: 'Stress on left element', value: field.stressRight[node - 1] / 1e6, unit: 'MPa' });
    if (node < field.positions.length - 1 && field.stressLeft) values.push({ label: 'Stress on right element', value: field.stressLeft[node] / 1e6, unit: 'MPa' });
  } else {
    values.push({ label: 'Temperature', value: field.values[node], unit: 'K' });
    if (node > 0 && field.flux) values.push({ label: 'Heat flux on left element', value: field.flux[node - 1], unit: 'W/m²' });
    if (node < field.positions.length - 1 && field.flux) values.push({ label: 'Heat flux on right element', value: field.flux[node], unit: 'W/m²' });
  }
  return values;
}

export const measuredNumber = (value: number) => Number(value.toPrecision(6)).toString();
