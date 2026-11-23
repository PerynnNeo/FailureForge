export function selectedScenarioBatch<T extends { id: string }>(batches: T[] | undefined, query: URLSearchParams) {
  const generation = query.get('generation');
  if (generation) return batches?.find(batch => batch.id === generation);
  if (query.get('reference')) return undefined;
  return batches?.[0];
}

export function scenarioGenerationHash(project: string, query: string, generation: string) {
  const next = new URLSearchParams(query);
  next.set('tab', 'scenarios');
  next.delete('reference');
  if (generation) next.set('generation', generation);
  else next.delete('generation');
  return '#/projects/' + encodeURIComponent(project) + '?' + next.toString();
}
