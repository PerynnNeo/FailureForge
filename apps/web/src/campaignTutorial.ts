import type { TutorialStep } from './HelpTutorial';
import type { Campaign } from './types';

export function campaignListGuide(hasMatches: boolean): TutorialStep[] {
  const steps: TutorialStep[] = [
    {
      target: 'campaign-create', title: 'Test a project across conditions',
      body: 'Choose New campaign, select a saved project, then configure its tests. Use a suite for several test definitions, a sweep for values of one input, or an environment matrix for combinations of supported conditions.',
    },
    {
      target: 'campaign-search', title: 'Find a saved campaign',
      body: 'Type part of a campaign name, project name or batch ID. Clear the search to see the full history again.',
    },
    {
      target: 'campaign-filter', title: 'Filter by progress or test type',
      body: 'Choose Active campaigns for ongoing work. Use the test type to find a project suite, sweep, environment matrix or bowl benchmark.',
    },
  ];
  if (hasMatches) steps.push({
    target: 'campaign-open', title: 'Open a campaign',
    body: 'Select a campaign name. In a project batch, choose View result beside a condition to watch its camera pair. A bowl benchmark opens its search results and recorded episodes.',
  });
  steps.push({
    target: 'campaign-benchmark', title: 'Run the bowl-placement benchmark',
    body: 'New bowl benchmark opens a separate experiment with a fixed robot and task. Choose LIBERO for simulated robot episodes or synthetic validation to check the software workflow.',
  });
  return steps;
}

export function projectCampaignGuide(hasProject: boolean): TutorialStep[] {
  const steps: TutorialStep[] = [{
    target: 'project-campaign-choice', title: 'Choose the prototype to test',
    body: 'Select the saved project that contains your model and acceptance criteria. You can review its goal and revision before continuing.',
  }];
  if (hasProject) steps.push({
    target: 'project-campaign-configure', title: 'Set up the batch',
    body: 'Configure campaign opens this project’s batch setup. Choose the supported tests, enter the conditions you want to compare, then review the inputs before starting the batch.',
  });
  return steps;
}

export function batchSetupGuide(mode: 'suite' | 'sweep' | 'matrix', modelSelected: boolean): TutorialStep[] {
  const steps: TutorialStep[] = [{
    target: 'campaign-batch-kind', title: 'Choose a test method',
    body: 'A suite runs a list of tests you define. A sweep varies one input. An environment matrix tests combinations of conditions. The menu shows the methods supported for this project.',
  }];
  if (mode === 'matrix') return [...steps, {
    target: 'campaign-matrix-values', title: 'Enter the operating conditions',
    body: 'Enter increasing parcel masses in kilograms and head forces in newtons. Select one value from each list for the reference. Name the matrix and choose Run environment matrix to queue every combination.',
  }];
  steps.push({
    target: 'project-model', title: 'Configure the model and inputs',
    body: 'Select the model, name the test and enter the inputs for this revision. For robot motion, check which robot is selected and match the joint targets to that robot.',
  });
  if (mode === 'sweep' && modelSelected) steps.push({
    target: 'campaign-sweep', title: 'Choose the input to vary',
    body: 'Select a numeric input. Enter between 2 and 16 increasing values, including the reference shown here. Run sweep queues one run per value.',
  });
  if (mode === 'suite') {
    if (modelSelected) steps.push({
      target: 'project-run', title: 'Add a test to the suite',
      body: 'Choose Add to suite to keep the current model, inputs and label. Change the inputs or choose another model and add another test. You can include up to 16.',
    });
    steps.push({
      target: 'campaign-suite-review', title: 'Name and run the suite',
      body: 'Enter a campaign name, check the test list, and remove any entries you do not need. Run suite queues these tests and opens their shared results.',
    });
  }
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
