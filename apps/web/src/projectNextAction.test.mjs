import test from 'node:test';
import assert from 'node:assert/strict';
import { projectNextAction } from './projectNextAction.ts';

const project = { id: 'shelf', revision: 2, analysis_type: 'structural', entry_stage: 'prototype',
  robot_source: 'custom', assets: [], task_phases: [], parameters: [] };
const run = { id: 'reference', label: 'Shelf under load', project_revision: 2, status: 'completed', adapter: 'structural_beam' };
const batch = { id: 'load-test', revision: 2, status: 'completed', candidates: [{ execution: { suite_id: 'test' } }], run_supported: true };
const discovery = { provider: { available: false }, batches: [] };

test('a brief needs a use case and a custom motion study needs a robot description', () => {
  assert.match(projectNextAction({ ...project, entry_stage: 'concept' }, [], discovery).action.href, /tab=phases$/);
  assert.match(projectNextAction({ ...project, entry_stage: 'concept', task_phases: undefined }, [], discovery).action.href, /tab=phases$/);
  assert.match(projectNextAction({ ...project, analysis_type: 'robot_behavior' }, [], discovery).action.href, /tab=files$/);
  assert.match(projectNextAction({ ...project, analysis_type: 'robot_behavior', robot_template: 'two_finger_hand_v1' }, [], discovery).action.href, /\/analysis$/);
  assert.match(projectNextAction(project, [], discovery).description, /beam dimensions/);
});

test('an explicitly prepared phase comparison takes precedence over an empty simulation form', () => {
  const prepared = { ...project, task_phases: [{ name: 'Place the parcel', conditions: [{ test: {} }] }] };
  const next = projectNextAction(prepared, [], discovery);
  assert.match(next.description, /Place the parcel/);
  assert.match(next.action.href, /tab=phases$/);
});

test('a saved generation with executions stays visible after a plan-only generation', () => {
  const plan = { ...batch, id: 'plan', candidates: [], run_supported: false };
  const next = projectNextAction(project, [run], { ...discovery, batches: [plan, batch] });
  assert.match(next.action.href, /generation=load-test$/);
  assert.match(next.alternative.href, /generation=plan$/);
  const planOnly = projectNextAction(project, [], { ...discovery, batches: [plan] });
  assert.match(planOnly.action.href, /\/analysis$/);
  assert.match(planOnly.alternative.href, /generation=plan$/);
});

test('old evidence can be reopened without presenting it as a current reference', () => {
  const old = { ...run, project_revision: 1 };
  const next = projectNextAction(project, [old], { ...discovery, batches: [{ ...batch, revision: 1 }] });
  assert.match(next.action.href, /\/analysis$/);
  assert.match(next.alternative.label, /revision 1/);
});

test('completed references link to discovery only when their workflow is available', () => {
  const offline = projectNextAction(project, [run], discovery);
  assert.match(offline.action.href, /run=reference$/);
  assert.match(offline.description, /AI is offline/);
  assert.doesNotMatch(offline.alternative.href, /tab=scenarios/);
  const online = { ...discovery, provider: { available: true } };
  assert.match(projectNextAction(project, [run], online).alternative.href, /tab=scenarios&reference=reference$/);
  assert.match(projectNextAction(project, [{ ...run, adapter: 'thermal_rod' }], discovery).alternative.href, /reference=reference$/);
  assert.doesNotMatch(projectNextAction(project, [{ ...run, adapter: 'robot_motion' }], online).alternative.href, /tab=scenarios/);
});

test('the guided shelf links to its recorded pair and an active generation links to its progress', () => {
  const next = projectNextAction(project, [run], discovery, 'paired-loads');
  assert.match(next.action.href, /tab=shelf&batch=paired-loads$/);
  const active = { ...batch, status: 'running', candidates: [] };
  assert.match(projectNextAction(project, [run], { ...discovery, batches: [active] }, 'paired-loads').action.href, /generation=load-test$/);
});
