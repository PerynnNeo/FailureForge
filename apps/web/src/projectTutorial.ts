import type { TutorialStep } from './HelpTutorial';

export type ProjectTourCapabilities = {
  hasModels: boolean;
  runCount: number;
  hasMatrix: boolean;
};

export const projectListGuide: TutorialStep[] = [
  {
    target: 'project-list-new',
    title: 'Start a project',
    body: 'New project opens a short setup form. You can begin with an idea, a design file, a working simulation or a physical prototype.',
    action: 'Choose this when you want a separate workspace for a design. You can add files, measurements and tests later.',
  },
  {
    target: 'project-list-entries',
    title: 'Return to a project',
    body: 'Saved projects appear here. Each card shows the project name, its goal and the materials already attached.',
    action: 'Select a card to continue. Inside the project, open Analysis & runs to find its recorded simulations. If the list is empty, use New project to begin.',
  },
];

export const projectSetupGuide: TutorialStep[] = [
  {
    target: 'project-setup-start',
    title: 'Starting point',
    body: 'Pick the card that describes what you have today. An idea can start with a task or sketch. For a CAD design, bring drawings or geometry. For a robot model, bring its description and controller.',
    action: 'Choose an existing simulation if you already have a test setup. Choose a physical prototype if you have built the device and can describe or measure its behavior.',
  },
  {
    target: 'project-setup-analysis',
    title: 'Choose the analysis',
    body: 'Robot behavior asks whether a task succeeds as conditions change. Strength & deformation asks how a part responds to a load. Heat & cooling asks what temperatures it reaches.',
    action: 'Pick the quantity you want to check. Read the note for your selection to see what this workspace supports.',
  },
  {
    target: 'project-setup-brief',
    title: 'Name the project',
    body: 'Use a name you will recognize in Your projects. A part name plus the question you are testing usually works.',
    example: '“Shelf bracket under load” makes the project easier to find than “Test 1.”',
  },
  {
    target: 'project-setup-goal',
    title: 'Describe the job',
    body: 'In “What should the design do?”, say what the prototype does and where it will operate. Include the outside condition that matters to the task.',
    example: 'A gripper should move a carton from the conveyor to the shelf even when the carton starts slightly off-center.',
  },
  {
    target: 'project-setup-criteria',
    title: 'Write a pass rule',
    body: 'In “Initial success criteria”, describe an observation that would count as a pass. Include a limit, unit or deadline when one applies. If the limit is provisional, say so.',
    example: 'Place the carton inside the marked area within 5 seconds and keep it upright.',
  },
  {
    target: 'project-setup-source',
    title: 'Choose the hardware source',
    body: 'Choose “My own design or existing project” for hardware you describe. Choose “Choose a catalog robot” to see the available references and what each supports.',
    action: 'For a catalog robot, select the template in the second field. When the brief is ready, use Create project to save it and open its workspace.',
  },
];

export const projectGuide: TutorialStep[] = [
  {
    target: 'project-journey',
    title: 'Read the project journey',
    body: 'The journey groups work into eight stages. The badges reflect what has been saved for this project. “Complete” on a preparation stage means the relevant inputs are present.',
    action: 'Open “What happens here” on a stage for its description. Use Analysis & runs whenever you want to see evidence from an actual run.',
  },
  {
    target: 'project-brief',
    title: 'Define the task',
    body: 'The working brief records the intended use and what would count as success. You can update the entry stage, analysis and hardware source as the design develops.',
    action: 'Describe the job under “What should the design do?” Put a measurable pass rule under “Success criteria” and uncertainties in the notes. Use Save changes to record this revision.',
  },
  {
    target: 'project-files',
    title: 'Prepare your files',
    body: 'If you have a source file, select its purpose to see the accepted formats. A drawing can document geometry, a robot description can describe joints, and a measurement file can record a physical test.',
    action: 'Choose a file and select Upload file. Open its inspection details to see what the app could read. You can leave Files empty while working on the brief.',
  },
  {
    target: 'project-parameters',
    title: 'Prepare your parameters',
    body: 'Use Parameters for values you want to keep with the design. Give each value a name, unit and source. Add a range if you know its lower and upper bounds.',
    action: 'Use Add parameter to enter a property and record where it came from. Save your changes. Where a run input offers a source selector, you can select a compatible saved parameter.',
    example: 'For a measured length, enter “Arm length”, the value 200, the unit mm, and the measurement source.',
  },
  {
    target: 'project-model',
    title: 'Review the model',
    body: 'The Analysis model selector lists what is available for this project. Its description tells you what the model represents. Selecting a model shows its inputs.',
    action: 'Compare those assumptions with the hardware and conditions in your brief. For a load test, for example, check where the model applies the load and how the part is supported.',
  },
  {
    target: 'project-tests',
    title: 'Design tests',
    body: 'A test plan records one repeatable scenario. Name it, describe the starting conditions, write the pass rule and specify which conditions may change.',
    action: 'Use Add test plan for a new scenario. Include a time limit if the task has a deadline, then save. You can use the plan when setting up a run.',
    example: 'For a carton pickup test, vary the starting offset from 0 to 5 mm while keeping the carton and controller the same.',
  },
  {
    target: 'project-qualification',
    title: 'Check the model inputs',
    body: 'The qualification stage asks whether the calculation is suitable for the question. Model input specification shows the fields and constraints for the selected analysis.',
    action: 'Check which fields are required, what units they use and whether their values describe your setup. If you have a known reference case, use it to check how closely the model matches.',
  },
  {
    target: 'project-run',
    title: 'Run tests',
    body: 'Run analysis uses the values entered for the selected model and records the saved project revision. Give the run a label that identifies its conditions.',
    action: 'Save any project edits, enter the planned inputs and use Run analysis when ready. To test several cases together, use Add to suite for each configuration and then Run suite.',
  },
  {
    target: 'project-history',
    title: 'Investigate a result',
    body: 'Run history shows the cases recorded for this project. Once a run is available, Inspect run opens its inputs, status and results. The evidence available depends on the selected analysis.',
    action: 'Choose the run by label or revision. Compare its reported result with your pass rule. If the case failed or stopped early, read the recorded checks or error details.',
  },
  {
    target: 'project-compare',
    title: 'Compare revisions',
    body: 'A baseline is the earlier run you want to compare with the selected run. Once you have comparable runs, the baseline selector lets you inspect their differences.',
    action: 'For a design change, repeat the same test conditions and pass rule on the new revision. Inspect the new run and select the earlier run under “Compare this run against a baseline.”',
  },
];

const matrixStep: TutorialStep = {
  target: 'project-matrix',
  title: 'Explore operating conditions',
  body: 'Each cell in an operating environment matrix represents one combination of conditions. Read the row and column labels to see what varied across the runs.',
  action: 'In a saved matrix, select a condition to see its recorded trace and checks. When the setup form is available, use it to choose conditions and a reference case for a new matrix.',
};

const unavailableModelStep: TutorialStep = {
  target: 'project-model',
  title: 'Review model availability',
  body: 'The project currently has no analysis model available to start a run. You can still describe the task, prepare inputs and save test plans.',
  action: 'Check the Analysis and Robot / hardware source selections in Overview against the design you intend to test.',
};

const emptyHistoryStep: TutorialStep = {
  target: 'project-history',
  title: 'Find future results',
  body: 'Run history is empty for this project. Recorded runs will appear here with their labels, project revisions and status.',
  action: 'After a run has been recorded, use Inspect run to open its inputs and available evidence.',
};

export function getProjectGuide(capabilities: ProjectTourCapabilities | null): TutorialStep[] {
  if (!capabilities) return projectGuide;
  const { hasMatrix, hasModels, runCount } = capabilities;
  const steps: TutorialStep[] = [];
  for (const step of projectGuide) {
    switch (step.target) {
      case 'project-model':
        if (hasMatrix) steps.push(matrixStep);
        steps.push(hasModels ? step : unavailableModelStep);
        break;
      case 'project-qualification':
      case 'project-run':
        if (hasModels) steps.push(step);
        break;
      case 'project-history':
        steps.push(runCount > 0 ? step : emptyHistoryStep);
        break;
      case 'project-compare':
        if (runCount >= 2) steps.push(step);
        break;
      default:
        steps.push(step);
    }
  }
  return steps;
}
