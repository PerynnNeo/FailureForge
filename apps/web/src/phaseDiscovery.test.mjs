import assert from 'node:assert/strict';
import test from 'node:test';
import { conditionSuggestions, phaseQuestions, phaseStarters } from './phaseDiscovery.ts';

const lift = { analysis_type: 'robot_behavior', robot_source: 'supported', robot_template: 'packaging_lift_v1' };

test('a compound lift answer surfaces independent mechanisms and never invents measured settings', () => {
  const ideas = conditionSuggestions(lift, 'A wet guide, variable press timing and an off-centre tray.');
  assert.deepEqual(ideas.map(item => item.status), ['physically_testable', 'awaiting_data', 'outside_model']);
  assert.equal(ideas[1].field, 'head_onset_ms');
  assert.equal(conditionSuggestions(lift, 'Different press dwell time')[0].field, 'head_duration_ms');
  assert.equal(ideas.some(item => item.test || item.changed_value), false);
});

test('questions and model suggestions follow the actual prototype and allow novel phases and conditions', () => {
  const robot = { ...lift, robot_source: 'custom', robot_template: null };
  assert.deepEqual(conditionSuggestions(robot, 'Variable press timing'), []);
  assert.deepEqual(conditionSuggestions(lift, 'Operators scan the shipping label twice'), []);
  assert.match(phaseQuestions(robot, 'Scan shipping label')[0], /Scan shipping label/);
  assert.ok(phaseStarters(lift).some(phase => phase.name === 'Release'));
  assert.ok(phaseStarters({ analysis_type: 'structural' }).some(phase => /instrument/.test(phase.question)));
  assert.equal(conditionSuggestions({ analysis_type: 'thermal' }, 'cool-down time')[0].status, 'outside_model');
});
