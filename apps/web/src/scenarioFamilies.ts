import type { Candidate } from './ScenarioReview';

/** Preserve the first occurrence of each family and the proposal order inside it. */
export function groupScenarioFamilies(candidates: Candidate[]) {
  const groups = new Map<string, { title: string; candidates: Candidate[] }>();
  for (const candidate of candidates) {
    const family = candidate.draft.missing_capability ? null : candidate.family_key;
    const key = family ? 'family:' + family : 'candidate:' + candidate.id;
    const existing = groups.get(key);
    if (existing) {
      existing.candidates.push(candidate);
    } else {
      const name = family?.split('.').at(-1)?.replace(/[_-]+/g, ' ') ?? '';
      groups.set(key, { title: name.charAt(0).toUpperCase() + name.slice(1), candidates: [candidate] });
    }
  }
  return [...groups.values()];
}
