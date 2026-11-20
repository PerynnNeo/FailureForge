import type { ProjectInput } from './projectTypes';

type Prototype = Pick<ProjectInput, 'analysis_type' | 'robot_source' | 'robot_template'>;
type Phase = { name: string; question: string };
type Suggestion = {
  label: string;
  status: 'awaiting_data' | 'physically_testable' | 'outside_model';
  reason: string;
  next_step: string;
  adapter?: string;
  field?: string;
};

const lift = (project: Prototype) => project.analysis_type === 'robot_behavior' &&
  project.robot_source === 'supported' && project.robot_template === 'packaging_lift_v1';

export function phaseStarters(project: Prototype): Phase[] {
  if (lift(project)) return [
    { name: 'Load the tray', question: 'Where does the parcel sit and how is it secured before the lift starts?' },
    { name: 'Rise', question: 'What touches, resists or applies force to the tray while it rises?' },
    { name: 'Hold', question: 'When does the press engage, for how long, and what else acts on the tray during the hold?' },
    { name: 'Release', question: 'How is the tray released and what changes as the next station takes the load?' },
  ];
  if (project.analysis_type === 'structural') return [
    { name: 'Set up supports', question: 'What sets the support position and how repeatable is the mounting?' },
    { name: 'Apply load', question: 'Where does the load enter, over what area, and can it move between uses?' },
    { name: 'Measure response', question: 'Where is displacement read, in which direction, and how is the instrument zeroed?' },
    { name: 'Unload', question: 'After removing the load, what movement or residual deformation needs checking?' },
  ];
  if (project.analysis_type === 'thermal') return [
    { name: 'Start up', question: 'What sets the initial temperatures and when do the surroundings or heat sources change?' },
    { name: 'Operate', question: 'Where is heat generated and which cooling surfaces are exposed, obstructed or in contact?' },
    { name: 'Cool down', question: 'What keeps generating or removing heat after the duty cycle ends?' },
  ];
  return [
    { name: 'Set up', question: 'What does the operator position or calibrate, and what might differ at another site?' },
    { name: 'Operate', question: 'Which objects, surfaces, signals or people interact with the prototype as it performs its task?' },
    { name: 'Handoff', question: 'What triggers the handoff and how could the surroundings affect release or recovery?' },
  ];
}

export function phaseQuestions(project: Prototype, phaseName: string): string[] {
  const name = phaseName.trim();
  const known = phaseStarters(project).find(phase => phase.name.toLowerCase() === name.toLowerCase());
  return [
    known?.question ?? `During ${name || 'this phase'}, what can the surroundings or operator change?`,
    'Which site, surface, load placement or supply condition could differ from the prototype’s usual setup?',
    'What starts or ends this step? Could another action occur early, late or at the same time?',
    'Which instrument or observation would show the effect, and where and when would you read it?',
  ];
}

// These are review prompts. Only the server can validate a runnable comparison.
export function conditionSuggestions(project: Prototype, answer: string): Suggestion[] {
  const words = answer.toLowerCase().replace(/[-‐‑–—_]/g, ' ').trim();
  if (!words) return [];
  const ideas: Suggestion[] = [];
  if (lift(project)) {
    if (/\b(guide|rail|slide|bearing)s?\b/.test(words) &&
        /\b(wet|damp|water|moisture|oily|dry|lubricat\w*|friction|stick\w*|dirty)\b/.test(words)) {
      ideas.push({ label: 'Measure guide resistance', status: 'physically_testable',
        reason: 'The lift model assumes a frictionless guide. Surface condition can change breakaway and running resistance.',
        next_step: 'Compare dry and affected guides at the same payload and speed. Measure breakaway force and running drag in newtons in each condition.' });
    }
    if (/\b(press|head)\b/.test(words) && /\b(tim\w*|early|late|delay\w*|onset|engag\w*|duration|dwell|pulse)\b/.test(words)) {
      const duration = /\b(duration|dwell|pulse width|how long)\b/.test(words);
      ideas.push({ label: duration ? 'Check press duration' : 'Check press engagement time', status: 'awaiting_data',
        reason: 'The timed lift accepts one prescribed downward force pulse. Its onset is measured from the start of the lift cycle.',
        next_step: 'Record the payload, nonzero press force, onset and duration. Confirm two operating values for the timing input and compare arrival and hold error.',
        adapter: 'packaging_lift_timed_v2', field: duration ? 'head_duration_ms' : 'head_onset_ms' });
    }
    if (/\b(off ?cent(?:er|re)(?:ed)?|eccentric|lateral offset|unevenly loaded|unbalanced)\b/.test(words)) {
      ideas.push({ label: 'Review eccentric loading', status: 'outside_model',
        reason: 'The lift has one vertical degree of freedom and a secured payload. It cannot resolve tray tilt, moments or unequal guide reactions.',
        next_step: 'Measure lateral offset from the guide centerline and tray tilt under load. A simulated comparison needs rotational motion and contact geometry.' });
    }
  }
  if (project.analysis_type === 'structural' && /\b(gauge|gage|probe|indicator)\b/.test(words)) {
    ideas.push({ label: 'Check the measurement setup', status: 'physically_testable',
      reason: 'The beam field gives displacement at recorded stations. Probe alignment, preload and zero error depend on the physical instrument.',
      next_step: 'Record distance from the clamp, sensing direction, initial reading and repeatability. Compare readings at the same station on the bench and in the simulation.' });
  }
  if (project.analysis_type === 'thermal' && /\b(warm ?up|cool ?down|cooling time|transient|start ?up time|duty cycle)\b/.test(words)) {
    ideas.push({ label: 'Measure the temperature transient', status: 'outside_model',
      reason: 'The rod solver predicts steady temperatures. It has no thermal storage or time-varying heat input.',
      next_step: 'Log temperature against elapsed time at a known location and record the duty cycle. A transient model also needs heat capacity and initial temperature.' });
  }
  return ideas;
}
