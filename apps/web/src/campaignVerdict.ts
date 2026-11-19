import { label } from './api';
import type { Condition } from './campaignCompare';

export function verdict(run: Condition) {
  if (run.error) return 'Inconclusive';
  if (run.status !== 'completed') return label(run.status);
  return run.passed == null ? 'Measurement only' : run.passed ? 'Passed' : 'Failed';
}

/** Render a single coordinate/input key-value pair the way the campaign table does. */
export function coordinateValue(key: string, value: unknown, field?: string | null) {
  if (key === 'payload_kg') return value + ' kg';
  if (key === 'head_force_n') return value + ' N';
  const name = key === 'value' ? field ?? 'input' : key;
  return label(name) + ' = ' + (typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value));
}

export function coordinateText(run: Condition, field?: string | null) {
  return Object.entries(run.coordinates).map(([k, v]) => coordinateValue(k, v, field)).join(' · ');
}
