import type { Inputs, RunSummary } from './analysisInputs';

export type Condition = Pick<RunSummary, 'id' | 'label' | 'adapter' | 'status' | 'error'> & {
  passed: boolean | null; reference: boolean; coordinates: Record<string, unknown>; metrics: Record<string, unknown>;
};

/** Conditions that reached a terminal completed state and can therefore carry evidence. */
export function completedConditions(runs: Condition[]): Condition[] {
  return runs.filter(run => run.status === 'completed');
}

export type ComparePair = { left: string | null; right: string | null };

/**
 * Choose the default left/right pair: left prefers the reference condition (else the first
 * completed one); right follows the case being inspected, then prefers a recorded failure.
 */
export function defaultPair(runs: Condition[], referenceId?: string | null, selectedId?: string | null): ComparePair {
  const completed = completedConditions(runs);
  const reference = referenceId && completed.some(run => run.id === referenceId) ? referenceId : null;
  const left = reference ?? completed[0]?.id ?? null;
  const available = completed.filter(run => run.id !== left);
  const right = available.find(run => run.id === selectedId)?.id
    ?? available.find(run => run.passed === false && !run.error)?.id ?? available[0]?.id ?? null;
  return { left, right };
}

/** Resolve a chosen pair of condition ids into their Condition records (null when unknown). */
export function resolvePair(runs: Condition[], pair: ComparePair): { left: Condition | null; right: Condition | null } {
  return {
    left: runs.find(run => run.id === pair.left) ?? null,
    right: runs.find(run => run.id === pair.right) ?? null,
  };
}

export type ChangedInput = { key: string; left: unknown; right: unknown };

/**
 * Diff two input/coordinate maps, returning only the keys whose values differ. Objects and arrays
 * are compared structurally; JSON object property order does not change an input.
 */
export function changedInputs(left: Inputs | undefined, right: Inputs | undefined): ChangedInput[] {
  const a = left ?? {}, b = right ?? {};
  const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])];
  const changes: ChangedInput[] = [];
  for (const key of keys) {
    if (!sameValue(a[key], b[key])) changes.push({ key, left: a[key], right: b[key] });
  }
  return changes;
}

function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => sameValue(v, b[i]));
  }
  const left = a as Inputs, right = b as Inputs;
  return Object.keys(left).length === Object.keys(right).length
    && Object.keys(left).every(key => Object.hasOwn(right, key) && sameValue(left[key], right[key]));
}
