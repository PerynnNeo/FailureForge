import type { TutorialStep } from './HelpTutorial';
import type { Campaign } from './types';

export function campaignListGuide(hasMatches: boolean): TutorialStep[] {
  const steps: TutorialStep[] = [
    {
      target: 'campaign-create', title: 'Set up a benchmark campaign',
      body: 'New campaign opens the setup form for the bowl-placement benchmark. You can explore camera and lighting changes with the same robot and task.',
    },
    {
      target: 'campaign-search', title: 'Find a saved campaign',
      body: 'Type part of its name or ID. Clear the search to see the full list again.',
    },
    {
      target: 'campaign-filter', title: 'Filter by progress or execution mode',
      body: 'Choose Active campaigns for ongoing work, Robot experiments for simulated robot runs, or Synthetic validations for generated workflow tests.',
    },
  ];
  if (hasMatches) steps.push({
    target: 'campaign-open', title: 'Open a campaign',
    body: 'Select a campaign name to inspect its scene changes, recorded episodes and any failure cases. The badge under each name identifies how it was run.',
  });
  return steps;
}

export const campaignSetupGuide: TutorialStep[] = [
  {
    target: 'campaign-name', title: 'Name the experiment',
    body: 'Enter a name you will recognize in the campaign list. Include the task and the conditions you plan to vary.',
    example: 'Bowl placement under dim lighting',
  },
  {
    target: 'campaign-mode', title: 'Choose what will run',
    body: 'Synthetic validation generates test data and can queue until its CPU worker connects. LIBERO runs the simulated robot policy and records both camera views. It becomes available when a qualified GPU worker connects.',
  },
  {
    target: 'campaign-method', title: 'Choose how to pick scene settings',
    body: 'Scrambled Sobol spreads settings across the chosen ranges. Uniform random samples independently. Sobol + local search starts with 16 Sobol settings and can then explore near observed failures.',
  },
  {
    target: 'campaign-budget', title: 'Set the number of settings to try',
    body: 'Choose 8, 16 or 32 candidates. Each is tested on two starting states after two initial reference checks. Choose 32 if you want the local search to run past its warm-up.',
    example: '8 candidates uses 16 search episodes plus 2 reference checks.',
  },
  {
    target: 'campaign-camera', title: 'Set the camera displacement range',
    body: 'Move the slider to the largest sideways offset to test, in centimetres on either side of the reference camera. The wrist camera remains attached to the robot.',
    example: '±0.5 cm allows positions from 5 mm left to 5 mm right of the reference position.',
  },
  {
    target: 'campaign-light', title: 'Set the lighting range',
    body: 'Move the slider to cover the lighting expected in your scene. The reference brightness is 1.00×. The worker samples between the displayed limits.',
    example: '0.90–1.10× covers lighting from 10% dimmer to 10% brighter than the reference.',
  },
  {
    target: 'campaign-seed', title: 'Choose a reproducible seed',
    body: 'Enter a whole number from 0 to 2147483647. Reuse it with the same search settings to repeat the initial candidate sequence. Local search also uses the outcomes it observes.',
    example: 'Use 42 for a first run.',
  },
  {
    target: 'campaign-start', title: 'Review and start',
    body: 'Check the episode count above this button. Start creates the campaign and queues its worker job. After submission, the campaign page shows progress and evidence as they arrive.',
  },
];

export function campaignDetailGuide(campaign: Campaign): TutorialStep[] {
  const steps: TutorialStep[] = [{
    target: 'campaign-progress', title: 'Check how far the campaign has run',
    body: 'The worker first checks the reference scene on two starting states. The budget shows completed episodes and the allowance for each phase. Some phases run only if a failure case is selected.',
  }];
  if (campaign.candidates?.length) steps.push(
    {
      target: 'campaign-plot', title: 'Explore the measured scene changes',
      body: 'Select a point to read its camera displacement and lighting multiplier. Color shows how many of the two search states failed. Gray points await a score. Blank space is untested.',
    },
    {
      target: 'campaign-candidate', title: 'Read a candidate’s outcome',
      body: 'Select a candidate number to highlight its point on the plot. Read across the row for its scene settings, failed states, proposal method and status.',
      example: '1 / 2 means one of the two search states failed at that setting.',
    },
  );
  if (campaign.episodes?.length) steps.push({
    target: 'campaign-episode', title: 'Inspect a recorded episode',
    body: 'Choose a phase or candidate and a starting state. Read the outcome, download its trace when available, or play the available robot camera recordings.',
  });
  if (campaign.jobs?.length) steps.push({
    target: 'campaign-jobs', title: 'Check the worker jobs',
    body: 'Read each job’s status and any error message. An interrupted job can resume within its existing allowance when the campaign has no active job.',
  });
  if (campaign.cases?.length) steps.push({
    target: 'campaign-witness', title: 'Investigate a failure case',
    body: 'Open a witness to compare the reference and changed scene on the same starting state. The case page also offers reduction, held-out confirmation and an evidence export.',
  });
  return steps;
}

export function caseGuide(canRerun: boolean): TutorialStep[] {
  const steps: TutorialStep[] = [
    {
      target: 'case-evidence', title: 'Compare the same starting state',
      body: 'Choose a recorded state and phase when available. Compare Reference with Changed, switch between Main and Wrist camera views, and inspect each trace. Synthetic cases contain generated numerical evidence.',
    },
    {
      target: 'case-reduction', title: 'Find a smaller change that still fails',
      body: 'Read the accepted and rejected changes here after a reduction. To start one, use Reduce witness above the tabs before requesting confirmation. It checks the original failure, tries smaller changes and verifies the retained setting.',
    },
    {
      target: 'case-confirmation', title: 'Test whether the effect holds on new states',
      body: 'Confirm case above the tabs freezes the chosen setting and queues 20 episodes on ten new starting states. When they finish, check here for how often the change caused a new failure or helped a state succeed.',
    },
    {
      target: 'case-provenance', title: 'Identify the saved configuration',
      body: 'Read the parent campaign, execution mode, failed states and exact camera and lighting settings here. Follow the parent campaign link to inspect its other candidates.',
    },
  ];
  if (canRerun) steps.push({
    target: 'case-rerun', title: 'Repeat the original comparison',
    body: 'Fresh paired rerun queues two new episodes from an original failing state, one reference and one changed. They appear alongside the original evidence. To review an existing recording, use Evidence.',
  });
  steps.push({
    target: 'case-export', title: 'Download the case',
    body: 'Export evidence saves a ZIP with the case manifest, episode data, available recordings and file checksums.',
  });
  return steps;
}
