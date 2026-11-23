export type WorkspacePreferences = {
  refreshIntervalMs: 0 | 4000 | 15000 | 60000;
  timeZone: 'local' | 'utc';
};

const key = 'failureforge.workspace.preferences.v1';
const defaults: WorkspacePreferences = { refreshIntervalMs: 4000, timeZone: 'local' };
const listeners = new Set<() => void>();

function validated(value: unknown, fallback: WorkspacePreferences): WorkspacePreferences {
  if (!value || typeof value !== 'object') return fallback;
  const { refreshIntervalMs, timeZone } = value as Partial<WorkspacePreferences>;
  return {
    refreshIntervalMs: refreshIntervalMs === 0 || refreshIntervalMs === 4000 || refreshIntervalMs === 15000 || refreshIntervalMs === 60000
      ? refreshIntervalMs : fallback.refreshIntervalMs,
    timeZone: timeZone === 'utc' || timeZone === 'local' ? timeZone : fallback.timeZone,
  };
}

function readSaved(): WorkspacePreferences | null {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    return null;
  }
  try {
    return raw ? validated(JSON.parse(raw), defaults) : defaults;
  } catch {
    return defaults;
  }
}

let current = readSaved() ?? defaults;
let sessionOnly = false;

function publish(next: WorkspacePreferences) {
  if (current.refreshIntervalMs === next.refreshIntervalMs && current.timeZone === next.timeZone) return;
  current = next;
  listeners.forEach(listener => listener());
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', event => {
    // A null key means another tab cleared storage for this origin.
    if (event.key !== null && event.key !== key) return;
    const saved = readSaved();
    if (saved) {
      sessionOnly = false;
      publish(saved);
    }
  });
}

export function getWorkspacePreferences(): WorkspacePreferences {
  return current;
}

export function subscribeWorkspacePreferences(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** Returns false when the change applies only for the current browser session. */
export function updateWorkspacePreferences(patch: Partial<WorkspacePreferences>): boolean {
  const next = validated(patch, sessionOnly ? current : readSaved() ?? current);
  try {
    window.localStorage.setItem(key, JSON.stringify(next));
    sessionOnly = false;
  } catch {
    sessionOnly = true;
  }
  publish(next);
  return !sessionOnly;
}

const timeFormatters: Partial<Record<WorkspacePreferences['timeZone'], Intl.DateTimeFormat>> = {};

export function formatWorkspaceTime(value?: string | number | null): string {
  if (value == null || value === '') return '—';
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  if (!Number.isFinite(date.getTime())) return '—';
  const { timeZone } = current;
  const formatter = timeFormatters[timeZone] ??= new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    ...(timeZone === 'utc' && { timeZone: 'UTC', timeZoneName: 'short' }),
  });
  return formatter.format(date);
}
