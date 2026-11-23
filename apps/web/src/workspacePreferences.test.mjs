import assert from 'node:assert/strict';
import test, { afterEach } from 'node:test';

// Each import represents a new browser page with storage for the same origin.
let pageId = 0;
const originalWindow = globalThis.window;
afterEach(() => {
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
});
async function page(entries, writesAllowed = true) {
  const tab = new EventTarget();
  tab.localStorage = {
    getItem: key => entries.get(key) ?? null,
    setItem(key, value) {
      if (!writesAllowed) throw new Error('Storage is unavailable');
      entries.set(key, value);
    },
  };
  globalThis.window = tab;
  const preferences = await import('./workspacePreferences.ts?page=' + ++pageId);
  return { ...preferences, tab };
}

test('validated settings survive reloads and apply to timestamp labels', async () => {
  const entries = new Map();
  const first = await page(entries);
  assert.deepEqual(first.getWorkspacePreferences(), { refreshIntervalMs: 4000, timeZone: 'local' });
  assert.equal(first.updateWorkspacePreferences({ refreshIntervalMs: 0, timeZone: 'utc' }), true);
  const reloaded = await page(entries);
  assert.deepEqual(reloaded.getWorkspacePreferences(), { refreshIntervalMs: 0, timeZone: 'utc' });
  const date = new Date('2026-11-23T23:30:00Z');
  const utc = new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', timeZoneName: 'short',
  });
  assert.equal(reloaded.formatWorkspaceTime(date.getTime() / 1000), utc.format(date));
  assert.equal(reloaded.formatWorkspaceTime(date.toISOString()), utc.format(date));
  assert.equal(reloaded.formatWorkspaceTime(null), '—');
});

test('changes in another tab notify subscribers and a storage clear restores defaults', async () => {
  const entries = new Map();
  const prefs = await page(entries);
  const updates = [];
  const unsubscribe = prefs.subscribeWorkspacePreferences(() => updates.push(prefs.getWorkspacePreferences()));
  prefs.updateWorkspacePreferences({ refreshIntervalMs: 15000 });
  const key = [...entries.keys()][0];
  entries.set(key, JSON.stringify({ refreshIntervalMs: 'broken', timeZone: 'utc' }));
  prefs.tab.dispatchEvent(Object.assign(new Event('storage'), { key }));
  assert.deepEqual(updates.at(-1), { refreshIntervalMs: 4000, timeZone: 'utc' });
  entries.clear();
  prefs.tab.dispatchEvent(Object.assign(new Event('storage'), { key: null }));
  assert.deepEqual(updates.at(-1), { refreshIntervalMs: 4000, timeZone: 'local' });
  unsubscribe();
  prefs.updateWorkspacePreferences({ refreshIntervalMs: 60000 });
  assert.equal(updates.length, 3);
});

test('blocked writes retain successive edits in the current tab', async () => {
  const prefs = await page(new Map(), false);
  assert.equal(prefs.updateWorkspacePreferences({ timeZone: 'utc' }), false);
  assert.equal(prefs.updateWorkspacePreferences({ refreshIntervalMs: 60000 }), false);
  assert.deepEqual(prefs.getWorkspacePreferences(), { refreshIntervalMs: 60000, timeZone: 'utc' });
});
