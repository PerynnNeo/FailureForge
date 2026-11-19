import type { Candidate } from './types';

/** The API score is a failure fraction over two states, never a state count. */
export function candidateFailureCount(candidate: Candidate): number | null {
  if (candidate.status !== 'completed') return null;
  const count = candidate.failure_count ?? candidate.failure_state_ids?.length
    ?? (candidate.score == null ? null : candidate.score * 2);
  return count !== null && Number.isInteger(count) && count >= 0 && count <= 2 ? count : null;
}
