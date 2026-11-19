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
 * completed one); right prefers the first completed non-reference condition that differs from left.
 */
export function defaultPair(runs: Condition[], referenceId?: string | null): ComparePair {
  const completed = completedConditions(runs);
  const reference = referenceId && completed.some(run => run.id === referenceId) ? referenceId : null;
  const left = reference ?? completed[0]?.id ?? null;
  const right = completed.find(run => run.id !== left && !run.reference)?.id
    ?? completed.find(run => run.id !== left)?.id ?? null;
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
 * are compared structurally via JSON.stringify so this is agnostic to project type.
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
  if (a === undefined || b === undefined) return false;
  if (typeof a === 'object' || typeof b === 'object') return JSON.stringify(a) === JSON.stringify(b);
  return false;
}
