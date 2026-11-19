export type Environment = { payload_kg: number; head_force_n: number };
export type MatrixRecord = {
  suite_id: string; project_revision: number; label: string; created_at: string | number;
  payload_kg: number[]; head_force_n: number[]; reference: Environment;
};
export type MatrixCell = Environment & {
  reference: boolean; run_id: string | null; status: string; passed: boolean | null;
  metrics: Record<string, unknown>; error: string | null; bundle_url: string | null;
};
export type MatrixDetail = MatrixRecord & {
  status: string; counts: { total: number; passed: number; failed: number; pending: number; blocked: number };
  cells: MatrixCell[];
};

export function axisValues(input: string, axis: string): number[] {
  const tokens = input.trim().split(/[\s,]+/);
  const values = tokens.map(Number);
  if (values.length < 2 || tokens.some((value, i) =>
    !/^(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value) || !Number.isFinite(values[i])
    || (i > 0 && values[i] <= values[i - 1]))) {
    throw new Error(`Enter at least two nonnegative, increasing values for ${axis}.`);
  }
  return values;
}

export function cellOutcome(cell?: Pick<MatrixCell, 'error' | 'passed' | 'status'>) {
  if (!cell) return 'Missing';
  if (cell.error) return 'Blocked';
  if (cell.status === 'running') return 'Running';
  if (cell.status === 'queued' || cell.status === 'pending') return 'Queued';
  if (cell.status === 'missing') return 'Missing';
  if (cell.status !== 'completed') return 'Blocked';
  if (cell.passed === null) return 'Unassessed';
  return cell.passed ? 'Passed' : 'Failed';
}

export function millimetres(metres: unknown) {
  if (typeof metres !== 'number' || !Number.isFinite(metres)) return '—';
  return new Intl.NumberFormat('en', { maximumFractionDigits: 3 }).format(1000 * metres) + ' mm';
}

export function liftHoldTrace(result: Record<string, unknown>) {
  const fixture = result.fixture as Record<string, unknown> | undefined;
  const series = result.series as Record<string, unknown> | undefined;
  const start = fixture?.arrival_deadline_s, end = fixture?.end_time_s;
  const target = fixture?.target_m, limit = fixture?.error_limit_m;
  const times = series?.time_s, positions = series?.position_m;
  const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
  if (!finite(start) || !finite(end) || start < 0 || end <= start || !finite(target) || !finite(limit) || limit < 0 ||
    !Array.isArray(times) || !Array.isArray(positions) || times.length !== positions.length) return null;
  const samples = [];
  for (let i = 0; i < times.length; i++) {
    const time = times[i], position = positions[i];
    if (!finite(time) || (i > 0 && time <= times[i - 1])) return null;
    if (time < start || time > end) continue;
    if (!finite(position)) return null;
    samples.push({ step: time - start, 'absolute height error (mm)': Math.abs(position - target) * 1000,
      'allowed error (mm)': limit * 1000 });
  }
  if (samples.length < 2) return null;
  const criteria = result.criteria as Record<string, unknown> | undefined;
  return { samples, showFirst: result.passed === false && criteria?.held_within_tolerance === false };
}
