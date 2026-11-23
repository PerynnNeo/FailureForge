import type { RunDetail, RunInput, RunSummary } from './analysisInputs';

const adapter = 'structural_beam';
const spreadLabel = 'Shelf example · evenly spread load';
const edgeLabel = 'Shelf example · load at the free edge';
export const shelfSuiteLabel = 'Shelf example · same weight in two positions';
export type ShelfInputs = {
  length_m: number; width_m: number; height_m: number; young_modulus_pa: number;
  elements: number; max_displacement_m: number; distributed_load_n_per_m: number; tip_force_n: number;
};

export function shelfInputs(value: unknown): value is ShelfInputs {
  if (!value || typeof value !== 'object') return false;
  const inputs = value as Record<string, unknown>;
  const positive = ['length_m', 'width_m', 'height_m', 'young_modulus_pa', 'elements', 'max_displacement_m', 'distributed_load_n_per_m'];
  return Object.keys(inputs).length === positive.length + 1 && inputs.tip_force_n === 0 && positive.every(key => {
    const number = inputs[key];
    return typeof number === 'number' && Number.isFinite(number) && number > 0;
  });
}

export function shelfTests(inputs: ShelfInputs): RunInput[] {
  return [
    { adapter, label: spreadLabel, inputs: { ...inputs } },
    { adapter, label: edgeLabel, inputs: { ...inputs, distributed_load_n_per_m: 0,
      tip_force_n: inputs.distributed_load_n_per_m * inputs.length_m } },
  ];
}

export function findShelfSuite(runs: RunSummary[]): string | undefined {
  const edges = new Set(runs.filter(run => run.adapter === adapter && run.label === edgeLabel).map(run => run.suite_id));
  return runs.find(run => run.suite_id && run.adapter === adapter && run.label === spreadLabel && edges.has(run.suite_id))?.suite_id;
}

export function savedShelfInputs(runs: RunDetail[]) {
  if (runs.length !== 2 || !findShelfSuite(runs)) return null;
  const [first, second] = runs;
  const inputs = first.inputs;
  if (!shelfInputs(inputs)) return null;
  const expected = shelfTests(inputs);
  if (runs.some((run, i) => run.label !== expected[i].label || run.project_revision !== first.project_revision)) return null;
  const changed = expected[1].inputs;
  if (Object.keys(changed).length !== Object.keys(second.inputs).length ||
      !Object.entries(changed).every(([key, value]) => second.inputs[key] === value)) return null;
  return inputs;
}

export function shelfReading(run: RunDetail) {
  if (run.status !== 'completed' || !run.evidence_hash || run.error || run.assessment_error) return null;
  const check = Array.isArray(run.result?.acceptance_checks)
    ? run.result.acceptance_checks.find(item => item?.quantity === 'continuous_max_abs_displacement_m') : null;
  if (!check || typeof check.passed !== 'boolean' || !Number.isFinite(check.measured) || !Number.isFinite(check.maximum)) return null;
  return { passed: check.passed, mm: check.measured * 1000, limitMm: check.maximum * 1000 };
}
