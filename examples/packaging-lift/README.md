# Can a packaging lift hold a tray under a packing head?

Packaging lines transport filled trays into a sealing station. This example models one positioning task in that workflow. A fixed lift raises a secured tray to **150 mm**. It must be within **10 mm** of the target at **1 second** and remain within that tolerance throughout the following second while a packing head pushes down. The carriage, controller, timing and acceptance rules are identical in every run. [OMRON tray sealer case study](https://files.omron.eu/downloads/latest/publication/en/tray_sealer_with_gripper_arms_machine_case_study_en.pdf)

## Measured simulation results

Each cell gives the maximum absolute position error during the one-second hold. The unrounded peak determines pass or fail. Every condition met the arrival deadline.

| Secured payload | No head force | 1 N downward | 2 N downward |
| --- | ---: | ---: | ---: |
| Empty | <0.01 mm · pass | 2.00 mm · pass | 4.01 mm · pass |
| 250 g | 4.91 mm · pass | 6.94 mm · pass | 8.97 mm · pass |
| 500 g | 9.81 mm · pass | **11.88 mm · fail** | **13.95 mm · fail** |

The 500 g payload used nearly the full error allowance even before the head engaged. The controller compensates for the weight of the empty carriage. At steady state, its proportional gain of 500 N/m requires about 2 mm of position error for each additional newton it must support. At 500 g and 2 N, the combined extra load is 6.905 N, implying a settled error of 13.81 mm. The trace reached 13.95 mm during the hold. The recorded peak actuator force during that hold was 17.12 N, below the 30 N limit. Checking only the arrival height would have passed all nine operating conditions. [Matrix evidence](../../output/verification/packaging-lift-matrix.json).

## Discover conditions that a completed grid missed

In **Packaging lift · task phase review**, the first campaign tested two parcel masses (0.15 and 0.50 kg) against two head forces (1 and 2 N). After all four cells completed, the operator used **Task phases** to add observations about rise, hold, tray loading and release. Open **Operating-condition coverage** on the original grid to see its four recorded cells alongside the later review. [Open the grid on the pilot PC](http://127.0.0.1:8000/#/projects/project_ef49d1d9990a4e849a45372bc5e5bbff/analysis?batch=suite_bbdee3c5fa804294b83a43dd2c31f2ed)

| Observation | Disposition in the project |
| --- | --- |
| The guide is wet after washdown | Physically testable. Compare breakaway and running resistance on dry and wet guides at matched load and speed. |
| Press engagement time varies | Modeled. Compare a 500 ms onset with a 1000 ms onset at the same force, pulse duration and payload. |
| A tray sits off-center | Outside the model. Record lateral offset and tilt. Simulation of guide reactions requires rotational motion and contact geometry. |
| Scanner acknowledgement arrives late | Awaiting data. Measure acknowledgement and release edges on a common clock. The operator entered this condition manually. |

For the simulated timing comparison, the operator chose illustrative settings of 0.30 kg, 2.5 N and a 250 ms pulse. At 1000 ms onset the peak hold error was **10.98 mm** and failed the 10 mm limit. At 500 ms onset it was **5.89 mm** and passed. These runs test the timing condition only. [Open the phase review](http://127.0.0.1:8000/#/projects/project_ef49d1d9990a4e849a45372bc5e5bbff?tab=phases) · [Recorded revisions, solver inputs and result hashes](../../output/verification/task-phase-coverage.json)

## Open or reproduce the example

1. In the local workbench, open **Projects → Packaging lift · tray mass and head force → Analysis & runs**. On a fresh installation, create a robot behavior project and choose **Packaging lift** from the catalog. [Open the verified matrix on this PC](http://127.0.0.1:8000/#/projects/project_3b75e02105b0465c9aedaa56294c5b6e/analysis).
2. In the operating-environment matrix, select a cell to inspect the stage checks, simulated height and forces. Each completed cell has its own evidence bundle. The empty tray with zero pressing force is the reference. Users can choose another reference when preparing a new grid.
3. To create or reopen the worked example via the API, start the local app and run the command below with the installed application Python. Repeating it reopens the same matrix for the same project revision.

```sh
python examples/packaging-lift/run.py
```

The matrix endpoint is `POST /api/projects/{project}/environment-matrices`. Its two axes must be in increasing order and include the declared reference. A grid contains up to 16 points. `GET /api/projects/{project}/environment-matrices/{suite_id}` returns the condition outcomes and links to each cell's evidence. The worked example supplies its exact request in [run.py](run.py).

An independent solver with networking disabled verified the full-load evidence bundle and reproduced the result exactly. From the repository root, run `failureforge project-bundle output/verification/packaging-lift-500g-2n.zip --rerun` to repeat the check. [Portable full-load case](../../output/verification/packaging-lift-500g-2n.zip).

## Model and scope

The fixed, 1 kg reference carriage uses the mass, travel, speed and 30 N actuator limit from the [vertical slide description](../../configs/vertical-slide.urdf). Its packing-station controller uses a proportional gain of 500 N/m, derivative gain of 40 N·s/m and fixed empty-carriage gravity compensation. Parcel mass contributes to weight and inertia for the entire cycle. A prescribed downward force switches on at 1 second. Each run evaluates two numerical integrations, checks the initial acceleration against the force balance, and searches the continuous position trajectory for its largest hold error. The supported factors are 0–1 kg and 0–5 N. [Equations and solver](../../src/failureforge/packaging_lift.py) · [Analytical regression checks](../../tests/test_packaging_lift.py).

The masses, forces and tolerance are illustrative inputs for a small reference fixture. The model assumes a secured payload and a frictionless guide. Real-machine comparisons would need measured payload, head-force and position histories from the same lift. Seal integrity, material deformation and temperature require separate tests.
