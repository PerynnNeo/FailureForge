# Execution PC and product verification

The local workbench runs in the `FailureForge-2404` Ubuntu 24.04 WSL2 distribution. Its persistent Linux checkout is `/opt/failureforge`, with the application database and evidence under `data/workbench`. From Windows, open [the local workbench](http://127.0.0.1:8000/). After a shutdown, start the application and qualified worker together from PowerShell:

```powershell
wsl -d FailureForge-2404 --cd /opt/failureforge -- bash scripts/start_workbench.sh
```

### Delivered scope

| Roadmap phase | Executed example and evidence |
| --- | --- |
| Project intake | Concept, CAD, model, simulation and prototype paths. The live examples retain uploads, source hashes, saved revisions, and test definitions. |
| Known robot | A fixed-palm two-finger MuJoCo model tracks joint setpoints under bounded feedback. The separately qualified SmolVLA benchmark executes a complete Panda bowl-to-plate manipulation task. |
| Import and preparation | STL units, extents, surface area, mesh preview and optional BOM mapping. Compatible URDFs support joint-tree checks and prescribed motion. Primitive models with the required inertias, collision geometry and actuator limits can run dynamic tracking with a declarative controller. The manufacturer OpenManipulator-X URDF was exercised in kinematic mode. |
| Repeated testing | Immutable test and project snapshots, durable per-test runs, finite parameter sweeps, cancellation, interrupted-job recovery, saved suites, parameter bindings and a CI comparison client. In a browser-driven regression, the same 5 N load exceeded the original cantilever's 0.10 mm deflection limit and passed on its revised geometry. |
| Physical calibration | A first-order model fitted to 2,056 published OpenManipulator-X samples produced a 46.69 ms time constant and 0.002844 rad RMSE on an independent 2,529-sample trial, within the declared 0.02 rad limit. Promoting a fit creates a new project revision and queues up to 16 distinct prior checks explicitly bound to that parameter. [Sources and reproducible study](../examples/openmanipulator-x/README.md). |
| Structural analysis | A one-dimensional linear-elastic cantilever finite-element solver reports displacement, stress, reactions, refinement checks and declared limits. A 100 N analytical fixture gave 1.042 mm tip deflection and 12.50 MPa peak bending stress. |
| Thermal analysis | A steady one-dimensional rod solver reports temperature, heat flow, balance and refinement checks. The live CAD/BOM reference is a 100 × 20 × 20 mm prism. Five heat-generation settings gave peak temperatures of 300, 305, 310, 315 and 320 K, with a 315 K acceptance limit. |

The engineering solvers use parameterized geometries and stated boundary conditions. General CAD conversion, nonlinear contact, fracture, transient thermal analysis, and physical safety certification require different models and validation. The prototype study covers one published joint and operating condition. Customer interviews, external engineering sign-off and public hosting are separate activities.

### RTX 5090 qualification

The host reported driver 591.86 and 32,607 MiB of GPU memory. Python 3.12.3, LeRobot 0.6.1, torch 2.11.0+cu128, MuJoCo 3.8.1 and EGL ran the pinned SmolVLA policy. A CUDA matrix check and both opt-in integration tests passed. Inference ran on CUDA. The WSL EGL platform probe reported Mesa software rendering.

| Attempt | Observation |
| --- | --- |
| `data/robot-01` | The first reset failed before an action. LIBERO looked for the tabletop scene relative to the installed package. Bootstrap now connects the verified asset snapshot at that path. |
| `data/robot-02` | Eight of ten qualification states and both search references succeeded. Exact image comparisons identified a timestamp mismatch between a cached settling frame and a freshly rendered scene. This attempt remained unqualified. |
| `data/robot-03` | The corrected probe rendered its independent reference on the untouched, settled scene. The exact identity, camera-only wrist invariance, lighting and reset checks passed. Eight of ten qualification states and both search references succeeded again. States 14 and 18 reached the 280-step horizon. |

The final qualification took 245 seconds. The main view showed the bowl and plate throughout the nine camera/light probes. The wrist camera showed the bowl and part of the plate near the top edge. Codex recorded the visual review after inspecting all eighteen native-resolution views. The local copy of `qualification.json` retains the reviewer identity, parameters, environment fingerprint and evidence hashes. Earlier attempts remain in their original directories.

### What changed when the camera moved

Two searches used seed 1729, eight candidate scenes per method, the same two initial states per candidate, and a 280-step limit. Both nominal reference runs succeeded in each campaign. Sobol produced two timeouts across its sixteen changed runs. Uniform random search produced three across its sixteen. This comparison covers one seed. [Sobol campaign](http://127.0.0.1:8000/#/campaigns/campaign_ee10e6f79c9f4acf8a7e8e3097984d79) · [Random campaign](http://127.0.0.1:8000/#/campaigns/campaign_984a58de6f04490e8066ac57ca20da6b).

In the selected Sobol case, state 0 succeeded under the nominal scene and reached the horizon with the main camera shifted **+10.32 mm** and lighting scaled to **1.1551×**. A bounded search evaluated twelve reduction proposals. With lighting restored to **1.0×**, a **+7.74 mm** shift still reproduced that failure. The final reduction also checked state 1. The shift is the smallest retained change among the proposals evaluated.

The scene was then frozen for ten previously unused initial states. The camera shift turned one nominal success into a timeout and two nominal timeouts into successes. Its effect depended on the starting state.

| Held-out result | State pairs |
| --- | ---: |
| Both scenes succeeded | 7 |
| Only the nominal scene succeeded | 1 |
| Only the shifted camera succeeded | 2 |
| Both scenes timed out | 0 |

The live worker reran the selected pair on state 0 and reproduced the original outcome. A second process verified the exported ZIP and imported it into an empty database. With all network interfaces disabled, fresh inference again succeeded under the reference camera in **89 steps** and exhausted **280 steps** under the shifted camera. The archive is 43,897,057 bytes and contains 72 episode manifests across 800 entries. Its SHA-256 is `5c6e3adc2a9431c2dd32efcef13d0f30ee55ba541dd9487c0b794cbf48d2e492`. [Machine-readable evidence](../output/verification/rtx5090-pilot.json) · [Demo recording](../output/demo/failureforge-demo.mp4).

The release also includes the physical calibration evidence. A clean solver with network access disabled verified all seven archive entries and reproduced the fitted time constant and held-out error exactly. Its solver source fingerprint had changed since the original run. [Calibration replay receipt](../output/verification/openmanipulator-replay.json) · [Data, robot description and licenses](../examples/openmanipulator-x/README.md).

In the live prototype project, revision 10 used an explicitly estimated 0.1 s response for the base joint. Its model predicted a 0.001832 rad endpoint error after a 0.1 rad step lasting 0.4 s, exceeding the 0.001 rad tolerance. Promoting the measured time constant created revision 11 and automatically repeated the same check. The model predicted a 0.000019 rad error and passed. The comparison verified that only the resolved time constant changed. Both revisions, the original measurement files and the two model predictions remain available in the workbench. [Promotion and comparison receipt](../output/verification/openmanipulator-promotion.json).

### Release verification

The final application suite passed 291 Python tests in 60.14 seconds. Its two opt-in hardware tests passed separately on this RTX 5090. All seven frontend tests, API type generation and the TypeScript/Vite production build passed. The Python suite emitted an upstream Starlette/AnyIO deprecation warning. The frontend build reported a 588 kB minified chunk for the illustrative 3D scene.

### Local examples

- [Two-finger hand tracking](http://127.0.0.1:8000/#/projects/project_015cd4cd52994b5eb4420606d4320f34)
- [Measured OpenManipulator-X calibration and model sweep](http://127.0.0.1:8000/#/projects/project_b91d43c26de543c5ac188d2918650e3e)
- [Cantilever revision comparison](http://127.0.0.1:8000/#/projects/project_29373a1fcf5f49f481c142674befc999)
- [Thermal sweep and CAD inventory](http://127.0.0.1:8000/#/projects/project_45e95407f1424ff39ac72c7d83a35ab0)
- [Real robot case and paired recordings](http://127.0.0.1:8000/#/cases/case_ac171e43247c4b79aae890f75f76bef3)
