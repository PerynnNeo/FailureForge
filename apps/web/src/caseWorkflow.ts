import type { CasePair, FailureCase, Job } from './types';

export function caseActionAvailability(jobs: Job[]) {
  const active = jobs.find(job => ['queued', 'running', 'cancelling'].includes(job.status));
  const reductionRequested = jobs.some(job => job.kind === 'reduce');
  const confirmationRequested = jobs.some(job => job.kind === 'confirm');
  return {
    active,
    latest: jobs.at(-1),
    reductionRequested,
    confirmationRequested,
    canReduce: !active && !reductionRequested && !confirmationRequested,
    canConfirm: !active && !confirmationRequested,
    canRerun: !active,
  };
}

export function evidencePairKey(pair: CasePair): string {
  const reference = pair.reference_episode_id ?? (typeof pair.reference === 'string' ? pair.reference : pair.reference?.id);
  const changed = pair.changed_episode_id ?? (typeof pair.changed === 'string' ? pair.changed : pair.changed?.id);
  return `${pair.state_id}:${reference ?? ''}:${changed ?? ''}`;
}

/** Preserve execution identity: the same state can have many distinct paired runs. */
export function collectCasePairs(item: FailureCase | null): CasePair[] {
  if (!item) return [];
  const groups: Array<[string, CasePair[]]> = [
    [item.reduction_final_pairs?.length ? 'final verification · selected' : 'original search · selected', item.pairs ?? []],
    ['original search', item.search_pairs ?? []],
    ['reduction initial verification', item.reduction_initial_pairs ?? []],
    ['reduction final verification', item.reduction_final_pairs ?? []],
    ['held-out confirmation', item.confirmation_pairs ?? []],
    ...(item.reruns ?? []).map((run, index): [string, CasePair[]] => [`fresh rerun ${index + 1}`, run.pairs]),
  ];
  const seen = new Set<string>();
  return groups.flatMap(([phase, pairs]) => pairs.flatMap(pair => {
    const key = evidencePairKey(pair);
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ ...pair, phase }];
  }));
}
