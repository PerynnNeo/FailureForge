# Testing a prototype across its operating environments

## Product decision

The first question in a project should be **“What job must this version of your prototype do, where, and what counts as success?”** The result should be a map of tested conditions, observed failures and gaps in the evidence. A team should be able to change its design later and repeat the same tests.

For example, a team installing one tabletop picking robot at two packing stations might have identical arms, grippers, cameras and software. Parts arrive at different positions and the two stations have different lighting. The useful test holds the installed hardware and software fixed and reproduces those operating conditions. Moving the camera becomes relevant if the deployment includes a removable mount, relocation between stations, or a specified installation tolerance. That calls for its own test plan.

## Where the current implementation fits

The LIBERO experiment qualified one Panda, one learned controller and one bowl-placement task. Its contract exposes camera translation and light intensity. Custom robot projects currently support bounded motion studies. An uploaded URDF can describe a mechanism, but completing an object-handling task also requires a controller that performs it, a modeled workcell and a way to determine whether the object actually reached the goal. The manufacturer's OpenManipulator-X model and the published joint-response records are valuable for testing one joint. They supply no physical observations of a robot grasping this bowl under different lighting. [Execution evidence](execution-host-results.md) · [Current project sweep inputs](project-sweeps.md)

In the recorded state-0 rerun, the reference and changed runs started from the same settled physical state and policy seed. The experiment set the external camera pose once before the first action. The learned policy issued different first commands. The target bowl rose **135.2 mm** in the reference run and **2.3 mm** in the changed run, locating the divergence in task performance at pickup or lift. The trace does not identify which visual feature led to the command change. To reproduce the measurement, open the two episodes under the Sobol case's `fresh_reruns` entry and use the free joint `akita_black_bowl_1_joint0` in each episode's `frames.json` layout. Its maximum recorded world z coordinate minus its initial z coordinate is the peak rise. [Episode IDs and outcomes](../output/verification/rtx5090-pilot.json) · [Paired recordings](http://127.0.0.1:8000/#/cases/case_ac171e43247c4b79aae890f75f76bef3)

Keep the qualification, job queue, revision snapshots, recordings, matched reruns and verified exports. The main addition is a project-owned task and environment definition that these services can execute. Keep the existing camera experiment accessible as a reference case.

## What an engineer would enter

| Part of the test | Example for the two packing stations |
| --- | --- |
| Prototype revision | Robot geometry and actuator limits, gripper, actual controller or policy build, sensor mounts and calibration. Identify the revision of each asset. |
| Task and acceptance rule | Transfer one specified part from the pickup area into the tray. Declare the goal region, release or dwell requirement, time limit and prohibited contacts before testing. |
| Operating environments | A profile per station with its fixture geometry, measured arrival region and lighting setup. Each includes a nominal condition and the conditions the user requires it to handle. |
| Factors allowed to vary | Part position in the table coordinate frame and illumination for a vision-controlled robot. Give values or bounds, units, evidence source and allowed combinations. Record whether a condition holds for the full run or changes at a specified event. |
| Model uncertainty | Record an uncertain friction estimate or actuator response separately. Measure it where possible. If evaluated across a range, show how the conclusion changes under that modeling assumption. |
| Evidence target | Name the conditions needed for a simulation decision and the observations needed to check the same behaviors on hardware. Track untested requirements explicitly. |

A different job, such as inserting the part into a fixture, gets a separate task and acceptance rule. A change to the customer's controller gets a new prototype revision. Each can reuse the same station description.

## Implementation sequence

1. **Version the task, environment and test matrix under the project.** Replace free-text variation with executable factors alongside the existing human brief. Each solver adapter declares supported tasks, factors, units, coordinate frames, limits, metrics and required assets. The UI offers a factor only when the adapter can implement it and the robot has a path through which it can affect the task. For example, lighting can feed a visual controller. Evaluating ambient temperature against motor performance requires an appropriate thermal and actuator model. An unsupported requirement remains visible with its missing dependency. [Project model](../src/failureforge/projects.py) · [Current experiment contract](../src/failureforge/contracts.py)

2. **Build one complete project workflow for tabletop placement.** Use the existing Panda task to qualify the runner. Keep both camera mounts and the learned controller fixed. Add a named bowl-placement input in table coordinates, applied before settling. Record the settled bowl, plate and robot poses and the light settings read back from the simulator. Check the neutral case against the existing baseline. Reject broken setups such as intersecting fixtures or a task already satisfied at reset. A valid, required pickup position the robot struggles to reach belongs in the results. If a site supplies lux readings, calibrate the mapping to the rendered scene before using lux labels. [Current scene adapter](../src/failureforge/simulation/libero.py)

3. **Run a coverage matrix before searching for failures.** A first demonstration could cross three specified pickup positions with two illumination settings. Those six cells are an illustrative test design. A customer's required ranges come from measurements or requirements. Predeclare the reference, repeat count, other randomized starting conditions, seeds and thresholds. For each paired comparison, match the background state and random inputs while applying the intended change. Report the absolute outcomes in both arms, including failures at nominal. After covering the required cells, search for hard combinations within the supported region and rerun discoveries on fresh trials. Reserve an independent test set for estimating performance across representative use. Extend single-input project sweeps to persist realized multidimensional cases and their common background conditions. [Sweep implementation](../src/failureforge/project_sweeps.py)

4. **Make results answer an operating decision.** Show a row per tested condition with attempts, successes, timeouts, completion times, task measurements and evidence links. A failure case should show what happened to the object as well as what the robot commanded. Mark invalid simulations, inconclusive results and untested combinations explicitly. Keep search-derived cases identifiable in exports. A deployment success estimate needs an appropriate trial design, sample size, uncertainty and information about how often conditions occur in service. Give the user two comparisons. The first shows one prototype across environments. The second shows two prototype revisions on identical environments and can reuse the existing regression machinery. [Revision comparison](../src/failureforge/project_runs.py)

5. **Qualify a customer prototype end to end.** Import one team's actual supported robot, behavior, fixture and task. Observe its nominal job and collect independent hardware trials at selected nominal, boundary and predicted-failure conditions. Record the realized setup, the object's trajectory or final state, timing, and the same acceptance metrics used in simulation. Predeclare tolerances for agreement. Keep discrepancies visible. If they motivate recalibration, issue a new model revision and verify on fresh measurements. The reference Panda remains a separate project. Physical validation applies to the prototype, job and conditions for which agreement was measured.

## Release criteria

- A new user can start from their prototype and intended job, identify missing inputs, and inspect the exact fixed and varied quantities before spending compute.
- A neutral scenario reproduces the qualified setup. For a changed scenario, tests verify that the requested environmental change reached the physics or sensor input while frozen design assets retain their identities.
- The reference demonstration runs the full six-cell matrix, preserves every attempted outcome, exports a representative failure if one occurs, and replays the selected pair. A matrix with no failures is a valid result.
- A design or controller revision can rerun the saved matrix with comparable conditions. The report shows where outcomes improved, deteriorated or stayed the same.
- A pilot with a real prototype can show the simulation prediction beside independent hardware observations, including disagreement and untested regions. Passing the reference demonstration establishes the workflow. The pilot measures its usefulness for that customer's operating decision.
