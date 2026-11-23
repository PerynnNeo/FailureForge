import type { RunSummary } from './analysisInputs';
import type { Project } from './projectTypes';

type Batch = {
  id: string; revision: number; status: string; run_supported?: boolean;
  candidates: { execution: unknown }[];
};

export type ScenarioActivity = { provider: { available: boolean }; batches: Batch[] };
type Action = { label: string; href: string };
type NextStep = { title: string; description: string; action: Action; alternative?: Action };
export const isWorking = (status: string) => status === 'running' || status === 'queued';

export function projectNextAction(project: Project, history: RunSummary[], discovery: ScenarioActivity, shelfSuite?: string): NextStep {
  const home = '#/projects/' + encodeURIComponent(project.id);
  const analysis = home + '/analysis';
  const files = { label: 'Add a robot model', href: home + '?tab=files' };
  const firstRun = { label: 'Set up a simulation', href: analysis };
  const runLink = (run: RunSummary) => analysis + '?run=' + encodeURIComponent(run.id);
  const batchLink = (batch: Batch) => home + '?tab=scenarios&generation=' + encodeURIComponent(batch.id);
  const runs = history.filter(run => run.project_revision === project.revision);
  const batches = discovery.batches.filter(batch => batch.revision === project.revision);
  const activeBatch = batches.find(batch => isWorking(batch.status));
  if (activeBatch) return {
    title: 'Your scenarios are being prepared',
    description: 'Open the batch to follow its progress. Each case will show what can be tested with this model.',
    action: { label: 'Follow scenario progress', href: batchLink(activeBatch) },
  };

  const tested = batches.find(batch => batch.candidates.some(candidate => candidate.execution));
  if (tested) return {
    title: 'Review your scenario tests',
    description: 'Open a case to see what changed, whether the simulation finished, and what it measured against the reference.',
    action: { label: 'Open scenario tests', href: batchLink(tested) },
    alternative: tested !== batches[0] ? { label: 'Open the latest generation', href: batchLink(batches[0]) } : undefined,
  };

  if (shelfSuite) return {
    title: 'Return to your shelf comparison',
    description: 'Follow both shelf loads and read how their simulated deflection compares with the design limit.',
    action: { label: 'Open shelf example', href: home + '?tab=shelf&batch=' + encodeURIComponent(shelfSuite) },
    alternative: batches[0] ? { label: 'Review scenario ideas', href: batchLink(batches[0]) } : undefined,
  };

  const batch = batches[0];
  if (batch && (batch.run_supported || batch.status !== 'completed')) return {
    title: 'Check what your scenario batch needs',
    description: batch.status === 'completed' ? 'Review the clarification requests and see which inputs or model capabilities the proposed cases need.' :
      'The last generation stopped before it finished. Open it to see the reason and review the setup.',
    action: { label: 'Review the batch', href: batchLink(batch) },
  };

  const reviewIdeas = batch && { label: 'Review saved ideas', href: batchLink(batch) };
  const latest = runs[0];
  if (latest) {
    const openRun = { label: 'Open this run', href: runLink(latest) };
    if (isWorking(latest.status)) return {
      title: 'Your simulation is in progress', description: latest.label,
      action: { ...openRun, label: 'Follow the run' }, alternative: reviewIdeas,
    };
    if (latest.status !== 'completed' || latest.error) return {
      title: 'See why your test stopped', description: 'Check the run details for the reason before starting another simulation.',
      action: openRun, alternative: reviewIdeas,
    };
    if (latest.reference_example) return {
      title: 'Inspect the reference hand example',
      description: 'This run used the built-in two-finger hand. Open it to inspect the motion, or upload a URDF to test your own robot.',
      action: openRun, alternative: files,
    };
    const thermal = latest.adapter === 'thermal_rod';
    const discoverable = ['structural_beam', 'packaging_lift', 'packaging_lift_timed_v2'].includes(latest.adapter);
    const canCompare = thermal || (discoverable && discovery.provider.available);
    const alternative = canCompare ?
      { label: 'Explore a changed condition', href: home + '?tab=scenarios&reference=' + encodeURIComponent(latest.id) } :
      reviewIdeas || { label: 'Set up another test', href: analysis };
    return {
      title: 'Read your simulation result', description: 'Open “' + latest.label + '” to see the model inputs, recorded measurements and any limits you set.' +
        (discoverable && !discovery.provider.available ? ' The local AI is offline. Your saved result is available.' : ''),
      action: { ...openRun, label: 'View the result' }, alternative,
    };
  }

  const priorRun = history.find(run => run.status === 'completed');
  const previous = reviewIdeas || (priorRun && { label: 'View result from revision ' + priorRun.project_revision, href: runLink(priorRun) });
  const phases = project.task_phases ?? [];
  const prepared = phases.find(phase => phase.conditions.some(condition => condition.test));
  if (prepared) return {
    title: 'Run the comparison you prepared',
    description: 'Open “' + prepared.name + '” in Task phases and choose Run comparison to test the reference and changed settings together.',
    action: { label: 'Open task phases', href: home + '?tab=phases' }, alternative: previous,
  };
  if (project.entry_stage === 'concept' && project.robot_source === 'custom' && !project.assets.length && !project.parameters.length) {
    const recorded = phases.flatMap(phase => phase.conditions);
    return {
      title: recorded.length ? 'Follow up on your recorded condition' : 'Describe one situation your design must handle',
      description: recorded[0]?.next_step || 'Choose a moment in the task. Write what could change and how you would tell if the design still works.',
      action: { label: phases.length ? 'Open task phases' : 'Describe a task phase', href: home + '?tab=phases' }, alternative: previous,
    };
  }
  if (project.analysis_type === 'robot_behavior' && !project.robot_template &&
      !project.assets.some(asset => asset.kind === 'robot_model' && asset.filename.toLowerCase().endsWith('.urdf')) &&
      !project.assets.some(asset => asset.kind === 'measurements')) return {
    title: 'Add the model for your first motion test',
    description: 'Upload the robot’s URDF under Robot description. You can then choose a joint and the position you want it to reach.',
    action: files, alternative: previous,
  };

  const setup = project.analysis_type === 'structural' ? 'Enter the beam dimensions, material stiffness and applied load to calculate how far it bends.' :
    project.analysis_type === 'thermal' ? 'Enter the rod dimensions, material conductivity and end temperatures or cooling conditions to calculate its steady temperature.' :
    project.robot_template === 'packaging_lift_v1' ? 'Choose a tray payload and pressing force to check whether the lift reaches its target and holds position.' :
    'Choose a motion test for your robot model, or use recorded joint measurements for a calibration.';
  return {
    title: priorRun ? 'Test the new version of your design' : 'Run your first simulation',
    description: setup + ' Use your usual operating conditions first so you have a result to compare with later.',
    action: firstRun, alternative: previous,
  };
}
