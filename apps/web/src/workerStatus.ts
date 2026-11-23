import type { Backend, Health } from './types';

export function workerFor(health: Health | null, backend: Backend) {
  return health?.workers?.[backend] ?? (health?.worker?.backend === backend ? health.worker : undefined);
}

export function workerLabel(health: Health | null) {
  const robot = workerFor(health, 'libero')?.online;
  const synthetic = workerFor(health, 'synthetic')?.online;
  if (robot && synthetic) return 'Robot and synthetic workers online';
  if (robot) return 'Robot worker online';
  if (synthetic) return 'Synthetic worker online';
  return 'Campaign workers offline';
}
