import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyProject, projectInput } from './projectTypes.ts';

test('editing older projects starts with an empty phase register and later edits preserve conditions and their tests', () => {
  const { task_phases: empty, ...older } = emptyProject();
  assert.deepEqual(empty, []);
  assert.deepEqual(projectInput(older).task_phases, []);
  const phase = {
    id:'press', name:'Hold', question:'When does pressure start?',
    conditions:[{ id:'timing', answer:'The press can start early.', question:'When does pressure start?',
      status:'modeled', reason:'The pulse onset changes.', next_step:'Compare hold error.',
      test:{adapter:'packaging_lift_timed_v2',field:'head_onset_ms',
        reference_inputs:{payload_kg:0.5,head_force_n:2,head_onset_ms:1000,head_duration_ms:1000},changed_value:500} }],
  };
  const edit = projectInput({ ...older, task_phases:[phase], revision:2 });
  edit.notes = 'Operating review continues.';
  assert.deepEqual(edit.task_phases, [phase]);
});
