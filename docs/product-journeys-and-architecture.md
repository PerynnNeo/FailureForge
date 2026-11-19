# FailureForge product journeys and technical architecture

Product and implementation specification

19 November 2026

## Purpose and reading guide

FailureForge should help a hardware team move from a design question to a reproducible investigation. Its central promise is to find conditions under which a supported robot fails a defined task, explain the measured sequence, and preserve the case so a revised design or controller can be tested again.

The product must welcome users at different stages without pretending that they all have an executable simulation. A sketch can produce a requirements and preparation plan. A CAD assembly can support model preparation. A qualified robot model and controller can support behavioral experiments. A physical prototype can supply measurements that improve the model. Structural and thermal questions require their own analysis engines and input requirements.

This document describes both the implemented foundation and the intended product. Sections describing the complete journeys are target workflows unless explicitly marked as available. Product delivery phases are separate from the stages an individual customer moves through. No throughput, completion dates, robot reliability, or certification claims are implied.

### Implementation status

| Layer | Status in this revision | Meaning for a customer |
|---|---|---|
| Local workbench and experiment engine | Existing implementation | Durable campaigns, bounded search, investigation, reduction, confirmation, paired reruns, and evidence export exist for the declared experiment contracts. |
| Synthetic diagnostic runner | Available for software verification | Exercises the application using mathematical diagnostic traces. Its results are not robot evidence. |
| Fixed LIBERO and SmolVLA integration | Implemented but awaiting target PC qualification | One Panda manipulation task with camera displacement and lighting variations. Real executions remain gated until qualification succeeds. |
| Project intake and readiness planning | Foundation introduced in this revision | Records the customer's development stage, inputs, assumptions, test intentions, and missing information. A preparation record is not an executed simulation. |
| Arbitrary robot uploads and general test execution | Planned | Require importers, controller interfaces, per-adapter capability checks, and model qualification. |
| Calibration, cross-version regression, structural and thermal execution | Planned | Each requires additional contracts, engines, validation, and pilot evidence. |

The existing live contract is intentionally narrow: pinned LeRobot and SmolVLA versions, one LIBERO Spatial bowl-to-plate task, main-camera x displacement from minus 0.04 to plus 0.04 metres, and lighting scale from 0.70 to 1.30. General-purpose robotics functionality must be added through new contracts rather than silently widening this contract.

## How a hardware idea becomes testable

A team normally starts with a job: hold a particular object, move a payload, fit in a workspace, or maintain a temperature. Engineers turn that job into requirements, mechanisms, parts, software, and test procedures. CAD, simulation, and physical prototypes can evolve together. A customer need not own a physical robot before beginning, but the confidence of the conclusions depends on the information and validation available.

“Mockup” is too ambiguous for an upload button. The intake should ask what the customer actually possesses: a drawing, a dimensioned assembly, a robot description, an executable simulation, or measurements from hardware. These are distinct assets with distinct uses.

### Information required for a meaningful experiment

| Information | Typical source | What FailureForge must establish |
|---|---|---|
| Geometry and assembly | CAD export or robot model with meshes | Units, scale, part identity, coordinate frames, missing files, and which parts move together. |
| Physical properties | CAD, datasheets, measurements, engineering estimates | Mass, inertia, joint limits, actuator limits, and the assumptions appropriate to the selected analysis. |
| Contact behavior | Material pairing, engineering estimates, measurements | Which surfaces interact, which contact model is used, and the uncertainty of its parameters. |
| Behavior | Controller package, policy, external controller connection, prescribed motion | Inputs, outputs, timing, joint mapping, operating limits, and reproducibility. |
| Task and environment | Customer requirements and scene assets | Initial conditions, objects, target outcomes, disturbances, and measurable failure rules. |
| Evidence of validity | Supplier provenance, model checks, reference runs, hardware logs | What was checked, what remains estimated, and which conclusions the evidence can support. |

Physical material assignments in CAD carry engineering properties; visual appearance alone does not. CAD systems may apply default materials, so an imported assignment needs review. Geometry and density can support approximate mass and inertia calculations, but assembly components and measurements may require overrides. These facts motivate explicit provenance rather than automatic trust. [Fusion material documentation](https://help.autodesk.com/cloudhelp/ENU/Fusion-Model/files/GUID-55EC2C42-60E1-48C7-B802-D2AA7AB6F0CB.htm) and [Onshape mass properties](https://cad.onshape.com/help/Content/View/mass_properties_tool.htm).

A material name also does not establish a calibrated contact model. “Silicone fingertip” is insufficient to determine friction against every object under every condition. FailureForge should make contact assumptions editable and encourage bounded uncertainty studies where measurements are unavailable.

### Three kinds of variable

The interface should separate variables that answer different questions.

| Kind | Example for a robotic hand | How it should behave |
|---|---|---|
| Design configuration | Finger length, motor choice, fingertip material | Produces a new hardware configuration and usually a new model revision. It may require rebuilding geometry, mass properties, and qualification. |
| Model parameter | Joint damping, estimated friction, motor delay | Describes the current modeled device. May be calibrated or varied over an explicit uncertainty range. |
| Test condition or disturbance | Object pose, payload, commanded speed, external perturbation | Changes the experiment while keeping the tested robot revision fixed. |

These categories can overlap physically, so the experiment records the intended interpretation. Changing friction to represent uncertain measurement is different from claiming that a manufactured replacement material improves the design. The result should retain that distinction.

Every parameter needs a name, unit, nominal value where known, permitted range where applicable, origin, evidence reference, and review status. Future execution adapters must additionally declare which parameters they can actually apply. A text field in a plan must never be mistaken for a simulator control.

## Shared customer lifecycle

The target lifecycle is Draft → Preparation → Model check → Test design → Qualification → Run → Investigation → Regression. Customers can enter at different stages, return to earlier ones, and maintain multiple revisions. Structural and thermal studies use equivalent gates with domain-specific checks.

| Stage | Customer action | System action and exit gate |
|---|---|---|
| Draft | Describe the product, stage, and engineering question. | Create a persistent project; route to the appropriate preparation path. |
| Preparation | Provide assets, properties, and assumptions. | Inventory inputs and identify missing or incompatible requirements. |
| Model check | Review scale, joints, materials, frames, and behavior mapping. | Validate package structure and supported features; retain a review report. |
| Test design | Define task, failures, variation ranges, and budget. | Check measurability, finite bounds, applicable variables, and engine capability. |
| Qualification | Inspect reference runs and accept a bounded operating envelope. | Verify the runtime and model execute sensibly before a search campaign. |
| Run | Start, monitor, cancel, or resume work. | Reserve budget, execute isolated attempts, and publish verified evidence. |
| Investigation | Compare conditions, replay, reduce, and reproduce. | Separate task failures from infrastructure errors and record evidence strength. |
| Regression | Compare a revised model or controller against saved tests. | Preserve old results, run the new revision, and report comparable changes. |

Readiness is multidimensional. Package completeness, model validity, controller compatibility, test definition, runtime availability, and physical calibration are separate indicators. A project can be ready for a scripted joint-range check and unready for autonomous grasp testing. Qualification applies to a specific model, controller, task, adapter, and runtime version; changing any consequential component can require requalification.

The UI should show a useful next action for every blocked gate. Examples include “provide joint limits,” “choose prescribed motion,” “replace the unresolved mesh,” or “run the reference task on the execution PC.” Passing a checklist is not an engineering certification. All requirements should be traceable to the analysis that needs them.

## Journey one from an idea or sketch

**Entry and inputs.** The customer has a concept, sketch, product rendering, or written requirement. They want to know what information to prepare and what failures will eventually matter. No mechanical model is assumed.

**Screens and actions.** The customer selects the concept stage, names the product, and describes its intended job. A target requirements screen asks about objects, payloads, workspace, expected motions, operating conditions, and unacceptable outcomes. The current foundation stores a working brief and allows reference files as attachments; it does not infer a mechanical model from them. The customer selects an analysis interest such as robot behavior, structural strength, or temperature.

**System behavior.** FailureForge produces a preparation plan organized by the chosen question. For a grasping hand, it requests articulated geometry, actuator information, a behavior source, contact assumptions, target objects, and success rules. It offers a supported example as an educational reference while keeping that example separate from the customer's proposed hardware.

**Gate and recovery.** The project remains in planning until a suitable model exists. Missing dimensions or unspecified behavior are actionable gaps, not simulated failures. The customer can revise requirements, recruit modeling assistance, or move to a supported robot path. An optional future assistant may suggest test questions, but generated text is reviewed planning material rather than measured evidence.

**Outputs and exit.** A requirements brief, asset checklist, assumption register, and draft test suite. The customer exits when the team can create or obtain the necessary model. A concept-only project receives no numeric reliability score or animation presented as its robot's behavior.

**Implementation.** Structured React forms, Pydantic input contracts, SQLite persistence, attachments, and downloadable planning JSON provide the foundation. Later assisted extraction can enrich it. Geometry reconstruction from images is outside the initial scope because a plausible shape would not establish mass, joints, or controller behavior.

## Journey two from CAD and a bill of materials

**Entry and inputs.** The customer has a dimensioned assembly, part materials, and a bill of materials. Some mechanical information may still be incomplete. They want to prepare a behavioral or engineering analysis before manufacturing.

**Screens and actions.** The intake records the assembly and export format. A future import screen inventories parts and external references. The customer confirms units, fixed and moving components, joint axes, material assignments, motors, and physical-property sources. A mapping screen links BOM entries and datasheets to the relevant components.

**System behavior.** The intended pipeline preserves source files, extracts supported metadata, and produces a reviewable model-preparation report. CAD export or a specialist CAD-to-robot exporter supplies the starting geometry and assembly information; FailureForge does not assume every CAD format preserves complete joints or actuator definitions. Collision geometry may need simplification independently of visual geometry. A preview should show both representations and the changes made.

**Gate and recovery.** Missing mass, ambiguous scale, unresolved components, unsupported mechanisms, or absent behavior prevent a behavioral run. Default materials are flagged for confirmation. The customer can supply measurements, enter an explicit estimate, replace an export, or narrow the intended analysis. Estimates may allow exploratory studies within stated bounds; they do not become measured values through acceptance.

**Outputs and exit.** A component inventory, material and property provenance, unresolved-issue list, prepared model candidate, and import report. The path exits into model check when the chosen adapter's requirements are satisfied. A CAD model with no controller can instead progress to the next journey's limited checks.

**Implementation.** Begin with explicit exports and assisted onboarding rather than a universal native CAD reader. Add isolated import workers and a canonical manifest that references original and derived assets by checksum. Geometry and material provenance should survive conversion. A structural study branches to its own meshing and load-definition workflow rather than reusing a rigid-body robot model indiscriminately.

## Journey three from a robot model without a controller

**Entry and inputs.** The customer supplies a supported robot description, meshes, joints, and physical properties but has not provided autonomous behavior. They want to inspect motion or begin preparing a testable system.

**Screens and actions.** The customer selects model preparation, resolves missing assets, and reviews a joint tree and coordinate frames. The behavior screen offers an explicit choice: attach a controller, define supported prescribed motion, or continue preparation only. The customer can specify a bounded joint sweep or a fixed motion sequence when that adapter supports it.

**System behavior.** Model checks inspect units, joint limits, collision representation, inertial validity, and supported features. A prescribed-motion test evaluates only the declared trajectory and modeled conditions. It may identify impossible commands, collisions, or limits, but it cannot establish how an absent autonomous controller would respond.

**Gate and recovery.** No autonomous task test is enabled without a compatible behavior source. Invalid inertia, numerical instability, or joint-map errors are setup failures requiring correction. A controller connected later must pass timing, observation, action, and reset checks; a successful import alone does not qualify it.

**Outputs and exit.** A validated package report, joint mapping, bounded motion evidence where supported, and a controller-integration checklist. The customer exits either with a useful geometry and motion review or with a model ready for controller qualification.

**Implementation.** Use adapter-specific model validators and a narrowly defined scripted-motion interface. MuJoCo is a candidate for an initial articulated-hand adapter; it is not a generic CAD importer. NVIDIA's documented manipulator workflow likewise includes physics configuration, tuning, controller mapping, and task validation after import. [NVIDIA manipulator workflow](https://docs.isaacsim.omniverse.nvidia.com/latest/robot_setup_tutorials/tutorial_manipulator_workflow.html).

## Journey four using a supported robot

**Entry and inputs.** The team uses an existing robot and wants to avoid constructing its model from scratch. They select a supported model and provide their intended task, objects, controller or permitted reference behavior, and deviations from the library configuration.

**Screens and actions.** A future library card displays model version, source, license, supported adapter, available behavior, validation status, and known limits. Selecting the robot creates a project revision. The customer reviews what matches their hardware, configures the task, and defines success and failure. Selecting a hand does not automatically supply every grasping skill.

**System behavior.** The adapter resolves a pinned asset package and verifies checksums. Changes to fingertips, motors, or geometry create a new configuration rather than altering the library baseline. A reference experiment demonstrates expected behavior in the supported environment before variations are enabled.

**Gate and recovery.** A listed model can be available as a preparation reference while execution remains unsupported. The UI must distinguish those statuses. If hardware differs from the reference, the customer documents the differences and validates their effect. Incompatible controllers return a concrete mapping or runtime error.

**Outputs and exit.** A versioned robot configuration, bounded reference report, supported variable list, and reusable experiment definition. After qualification the customer progresses to campaigns and investigation.

**Implementation.** LEAP Hand is a reasonable candidate for a first hand integration because publicly maintained model assets exist. MuJoCo Menagerie supplies a LEAP model, while the LEAP project supplies an Isaac Lab reorientation implementation. These are different integration paths: an Isaac-trained policy is not automatically qualified in MuJoCo. Choose and validate one coherent model, behavior, simulator combination first. [MuJoCo Menagerie LEAP assets](https://github.com/google-deepmind/mujoco_menagerie/tree/main/leap_hand) and [LEAP Isaac Lab project](https://github.com/leap-hand/LEAP_Hand_Isaac_Lab).

## Journey five bringing a working simulation and running multiple tests

**Entry and inputs.** The customer already has a runnable scene, robot, controller, dependencies, and at least one reference task. They want repeatable stress tests and comparisons without manually setting up every run. This is the strongest initial customer hypothesis because much of the modeling work already exists.

**Screens and actions.** The customer selects an existing-simulation path and supplies a supported manifest or approved local integration. A compatibility screen shows adapter version, observations, actions, reset behavior, assets, and available metrics. The test designer creates several independently defined tests, such as hold, rotate, and recover. Each specifies initial conditions, horizon, success, failure, variables, reference values, and budget.

**System behavior.** Preflight rejects incompatible interfaces and missing assets. Qualification runs references for each task. The scheduler then executes a suite while retaining task boundaries, per-test budgets, original seeds, and all attempts. Parameter search proposes bounded conditions; it does not invent a task the controller cannot perform. Tests with different task semantics are reported separately before any overall summary.

**Gate and recovery.** One invalid task need not invalidate the project, but it cannot silently count as a robot failure. The suite should show qualified, blocked, running, cancelled, and completed tests separately. Timeouts, renderer faults, invalid states, and corrupted artifacts are infrastructure or model errors. They remain visible and consume the configured budget policy.

**Outputs and exit.** A suite report, per-test coverage, failure cases, matched reference and changed-condition replays, measurement traces, and reproducible exports. “No failures observed” is a valid result within the tested conditions. Search-generated samples do not by themselves estimate everyday failure probability.

**Implementation.** Extend the existing durable queue and episode records with a suite parent and adapter-specific test contracts. Preserve bounded budgets, idempotency, lease fencing, cancellation, and immutable publication. Multi-task orchestration is a new capability; today's fixed campaign engine must not be presented as a general suite runner.

## Journey six calibrating against a physical prototype

**Entry and inputs.** A physical robot and a simulation exist. The customer has timestamped commands and sensor logs, model revisions, test conditions, and information about the measurement equipment. They want the simulation to better reflect observed behavior.

**Screens and actions.** The customer registers the physical hardware configuration and maps log columns to units, joints, commands, and clocks. A calibration setup screen selects parameters to estimate, allowed ranges, representative runs, and a separate validation set. The user reviews synchronization, missing samples, coordinate conventions, and measurement uncertainty before fitting.

**System behavior.** A future calibration worker replays equivalent commands in the model and compares selected observables. It proposes parameter values with residuals and limitations. The customer checks held-out runs before promoting a candidate calibration. Model mismatch remains explicit when no parameter setting explains the measurements sufficiently.

**Gate and recovery.** Missing timestamps, conflicting units, unknown hardware changes, or unobservable parameters can block fitting. The product should recommend a better measurement plan rather than returning arbitrary precise values. A calibrated parameter set is scoped to its data and operating range. Accepting a fit creates a new model revision and may trigger requalification.

**Outputs and exit.** A calibration report, original data references, fit and validation partitions, residual plots, accepted parameter revision, and unresolved discrepancies. The customer then reruns saved simulation cases and decides which require controlled physical validation.

**Implementation.** Start with explicit CSV or documented log schemas and selected low-dimensional parameters. More formats can be added after pilot evidence. MuJoCo describes fitting parameters by comparing simulated and recorded measurements, supporting this proposed direction. [MuJoCo system identification](https://mujoco.readthedocs.io/en/stable/modeling.html#system-identification). FailureForge should not automatically command physical hardware in this workflow; hardware execution requires a separately designed integration.

## Journey seven repeated testing of product revisions

**Entry and inputs.** A team has qualified experiments and saved failures. They are changing a controller, mechanical component, calibration, or environment and need to know whether a revision improves the cases they care about.

**Screens and actions.** The customer creates a new immutable revision, selects a baseline, chooses a regression suite, and reviews changed dependencies. The comparison screen identifies whether each test remains directly comparable. The customer can add previously unseen cases to avoid judging a revision solely on the failures it was designed to fix.

**System behavior.** The proposed runner executes the same declared tests against both relevant revisions or verified retained reference evidence, according to an explicit comparison policy. It reports new failures, resolved failures, unchanged outcomes, execution errors, and untested conditions. Repeated trials preserve paired states where appropriate. Changed thresholds or tasks are called out because they alter the interpretation.

**Gate and recovery.** Missing baseline assets, changed observation meanings, incompatible tasks, and failed requalification block the relevant comparisons. An interrupted run preserves completed evidence and resumes through the durable queue. Existing evidence is never overwritten by a later run.

**Outputs and exit.** A revision comparison report, per-case evidence, measured coverage, unresolved failures, and a saved release-test definition. The customer makes the release decision; a green suite means the declared tests passed under their modeled conditions.

**Implementation.** Add revision identities, suite snapshots, comparison policies, and a CLI suitable for a customer's CI pipeline. The existing paired rerun feature is a useful building block but does not yet implement general cross-version regression. Authentication, project permissions, and team review history become necessary before shared hosting.

## Journey eight structural analysis of a component

**Entry and inputs.** The customer asks whether a finger, bracket, or housing bends excessively or exceeds a material criterion. They provide suitable geometry, material properties, connections, loads, supports, and an engineering interpretation of the relevant limit.

**Screens and actions.** The customer selects structural analysis, associates materials with bodies, assigns constraints and loads, reviews the mesh, and chooses supported study assumptions. A review screen identifies missing restraints, unsupported contacts, questionable material data, and the limits of the selected analysis type.

**System behavior.** A future finite-element adapter creates a solver input, runs it, and returns displacement and stress fields with convergence and solver diagnostics. The product should compare mesh refinements where the study requires them. A stress concentration at a sharp mathematical corner cannot be treated automatically as a reliable crack prediction.

**Gate and recovery.** Inadequate restraints, invalid meshes, unconverged solutions, and unsuitable material models prevent an accepted result. The customer adjusts geometry, boundary conditions, mesh, or analysis scope. Fatigue, fracture, anisotropic printing, and complex nonlinear contact need explicit support and validation beyond a first linear-static integration.

**Outputs and exit.** A study package containing geometry revision, mesh, loads, constraints, material provenance, solver identity, field results, and validation checks. The customer can compare design revisions once the studies are comparable.

**Implementation.** Gmsh is a candidate meshing tool and CalculiX a candidate structural solver; an established commercial solver connector is an alternative for pilot teams already using one. Selection depends on supported problems, licensing, redistribution, and validation effort. Their availability does not make the integration implemented. [Gmsh documentation](https://gmsh.info/) and [CalculiX project](https://www.calculix.de/).

## Journey nine thermal analysis of a component

**Entry and inputs.** The customer asks about temperature under a specified operating cycle. They provide geometry, thermal properties, heat sources, ambient conditions, relevant contact interfaces, cooling assumptions, initial conditions, and temperature criteria.

**Screens and actions.** The customer chooses a supported steady-state or transient study, maps materials and heat inputs, assigns boundaries, and reviews the modeled cooling conditions. If motor heat generation is estimated, that estimate and its range are explicit; a motor part number alone does not supply a complete duty-cycle thermal model.

**System behavior.** A future thermal adapter produces a temperature field and, for transient studies, temperatures over time. It records heat-balance and convergence diagnostics where supported. The system can vary ambient temperature or duty cycle only when the adapter defines how those controls affect the model.

**Gate and recovery.** Missing thermal conductivity, unspecified heat generation, inadequate boundary conditions, or an unconverged solve require correction. If airflow materially determines cooling, a simple assumed convection coefficient may be inadequate; the study should narrow its claim or use a validated higher-fidelity method.

**Outputs and exit.** A reproducible thermal study, maximum-temperature locations, time histories, assumptions, and a bounded comparison against the customer's criterion. Structural and thermal analyses may later share geometry, but coupled analysis requires a separate validated contract.

**Implementation.** Elmer is a candidate multiphysics framework for a thermal adapter; CalculiX also documents thermal capabilities. The team should evaluate a small reference problem set before choosing a backend. These are planned engine decisions, not installed or validated product features. [Official Elmer repository](https://github.com/ElmerCSC/elmerfem) and [CalculiX capabilities](https://www.calculix.de/).

## What the new project foundation does now

The implemented project layer makes these entry paths concrete without exposing unimplemented execution controls. It is separate from the existing fixed-benchmark workbench. A saved custom project does not change the robot used by that benchmark.

### The delivered user flow

1. Open **Projects** at `#/projects` and create a project.
2. In **Starting point**, choose concept, CAD, robot model, working simulation, or physical prototype.
3. In **Analysis**, choose robot behavior, structural, or thermal analysis. This choice changes the preparation requirements; all new project execution remains unavailable.
4. In **Project brief**, enter a name, working goal, and success criteria. A concept needs no robot file to begin.
5. Review **Overview** for the brief, readiness checks, next action, and lifecycle. Supported robot choices are preparation references, not installed model packages.
6. Add relevant assets in **Files**. Small supported XML robot descriptions receive bounded structural inspection. Syntax and counts are not physics qualification.
7. Record values in **Parameters**, including units, origin, optional ranges, and evidence. “Measured” and “calibrated” are user-provided provenance labels rather than independently verified claims.
8. Create several **Test plans**, each with an objective, success criteria, proposed variation, and optional timeout.
9. Save changes and export a JSON project report for review or handoff.

Edits use a revision check to prevent silent overwrites. Uploads wait until metadata edits are saved, so an upload cannot discard an unsaved project draft. Readiness recalculates from persisted inputs after saves and uploads. A completed checklist item means its declared preparation condition is present, not that the model has passed a scientific validation.

### Current boundaries

The project service accepts at most 40 assets per project and 10 MiB per asset, with a stricter 2 MiB limit for XML and JSON inputs. It records up to 80 parameters and 30 test plans. XML document type declarations and entities are rejected; parsing is bounded. Robot-description inspection can count elements and flag missing explicit properties or unresolved resource references, but it does not resolve the complete asset graph, verify dynamics, install packages, or execute code.

Uploaded assets are otherwise opaque attachments. Archives are not extracted, controller scripts are not run, CAD is not converted, and JSON is not treated as an executable experiment merely because it parses. Files can be downloaded and the planning record exported. The execution gate for every new project is explicitly false. The existing synthetic and fixed-benchmark routes retain their own contracts and gates; the real benchmark adapter still awaits target PC qualification.

| File purpose | Accepted examples in the foundation |
|---|---|
| CAD | STEP, STL, OBJ, IGES, GLB, glTF, PLY. |
| Robot model | URDF, MJCF, XML, JSON. |
| Controller reference | Python, JSON, YAML, text, ZIP, ONNX, PT, PTH. Stored only. |
| Bill of materials | CSV, JSON, text, XLSX. |
| Scene | USD variants, XML, JSON, GLB, glTF, ZIP. |
| Measurements | CSV, JSON, text. |
| Requirements and sketches | PDF, text, Markdown, JSON, PNG, JPEG, WebP. Images are stored as supplied. |

Large model checkpoints may exceed these preparation limits. Record their identity and location in the brief; a future controlled asset-transfer mechanism is required before such packages can execute.

These boundaries allow teams at every researched stage to organize a real preparation record now. They also make the next engineering work visible instead of displaying invented results.

## A hand project progressing through the product

Consider a team designing a hand to rotate small objects. This example describes future workflow behavior; it contains no measured robot results.

At concept stage, the team records a rotation goal and defines “drop” and “timeout.” At CAD stage, it adds finger geometry, materials, a motor BOM, and estimated physical properties. Model preparation exposes a missing joint axis and an uncertain fingertip contact parameter. The team resolves the axis and records a friction interval rather than guessing an exact calibrated value.

With only the model, the team runs a supported prescribed-motion check after that capability is implemented. After attaching its controller, it qualifies one rotation task. The test suite varies initial object position, friction assumptions, and object mass. Camera and lighting controls are absent if the controller consumes no images.

A discovered case might show contact loss followed by a drop. The customer sees the measured sequence, recreates the same case, and explores which changes were necessary. The system does not label the fingertip material as the cause merely because friction was varied.

The team later uploads prototype logs, validates a calibration revision, and reruns saved cases. A controller revision may resolve some cases and introduce others. If the question becomes whether a finger cracks or a motor overheats, the same project gains a separate structural or thermal study with its own additional inputs. The robot task simulation does not retroactively establish those answers.

## Technical architecture

### Existing foundation and additive implementation

The application uses React and TypeScript in the browser, a FastAPI HTTP service, Pydantic contracts, SQLite persistence, and a separate worker process. The browser does not execute GPU simulation. The existing engine reserves episode allowances, persists proposals and attempts, fences worker completion through leases, and exposes artifact records after verified publication. These mechanisms should remain the foundation of new executable adapters.

The project layer adds project and asset storage without changing existing campaigns. The current API is:

| Endpoint | Purpose |
|---|---|
| `GET /api/projects/catalog` | Entry stages, analysis types, reference robot choices, and input guidance. |
| `GET` and `POST /api/projects` | List projects and create a validated planning record. |
| `GET` and `POST /api/projects/{id}` | Read and update a project; updates require the expected revision. |
| `POST /api/projects/{id}/assets` | Upload raw bytes with filename and asset kind parameters. |
| `GET /api/projects/{id}/assets/{asset_id}` | Download the stored attachment. |
| `GET /api/projects/{id}/export` | Export the project and preparation report as JSON. |

The project contract records stage, analysis type, goal, success criteria, custom or supported source, optional robot reference, notes, parameters, and test plans. Readiness returns checks with complete, missing, review, or blocked statuses; descriptive lifecycle phases; limitations; a next action; and the explicit execution gate. These are planning data, distinct from actual episode outcomes.

### Data model for subsequent phases

The next execution architecture should add immutable identities for model revision, controller revision, environment revision, adapter version, test specification, qualification record, suite snapshot, and calibration revision. A run references exact identities rather than the latest mutable project. Assets retain source filename, media type, size, checksum, import status, and provenance. Derived meshes and converted models reference their source assets and conversion settings.

A test definition describes parameter applicability, units, bounds, initial-state generation, horizon, observables, success and failure predicates, reference conditions, and budget. A suite groups these definitions without merging their meanings. A case links observed failure evidence to the exact experiment and configuration. A regression comparison references both revisions and states whether its measurements are comparable.

This separation permits a customer to change a draft without modifying historical results. Later project-level collaboration requires permissions, an audit trail, explicit retention settings, and revision history. Those features should be added deliberately before multi-user hosting.

### Adapter contract

An execution adapter should expose five clear responsibilities:

1. **Capabilities** declare supported assets, mechanisms, controllers, analyses, variables, observables, and limitations.
2. **Validation** checks package structure, dependencies, model semantics, controller interfaces, and test compatibility.
3. **Qualification** executes reference checks and returns evidence tied to model and runtime identities.
4. **Execution** resets an experiment, applies supported variations, advances it within budgets, and classifies termination.
5. **Evidence** publishes traces, recordings or fields, metrics, configuration identities, diagnostics, and limitations.

The adapter owns the meaning of a variable. The shared search service proposes values only within declared bounds. The UI renders supported controls from the capability contract rather than assuming all engines support lighting, friction, torque, or heat sources. Domain-specific error categories distinguish a task failure, invalid model, numerical failure, infrastructure interruption, and incomplete evidence.

### Runtime and deployment

The initial deployment remains local or private. The laptop can serve as a browser and preparation workstation while the execution PC hosts the worker. Keep model and simulator environments separate from the lightweight application environment, pin dependencies, and qualify the exact runtime. The existing setup uses same-host service and worker coordination; remote dispatch is a future feature rather than an implied browser capability.

A 5090 PC is useful for compatible GPU workloads, but it does not make every solver GPU accelerated or remove CPU, memory, storage, and contact-complexity limits. Measure throughput after qualification. Start with conservative concurrency and record resource use; budgeted campaigns should not assume a promised number of simulations per hour.

Future user-provided controllers and importers require isolated execution with restricted filesystem access, resource and time limits, controlled dependencies, and an explicit network policy. The current opaque upload path must not evolve into arbitrary script execution inside the API process. A hosted service additionally requires tenant isolation, authenticated authorization, transport protection, upload quotas, retention controls, and separate worker trust boundaries. Solver and asset licenses must be evaluated before redistribution or hosted commercial use.

### Evidence quality and interpretation

Every result should retain the model, controller, task, simulator, search settings, seeds, and source parameters that produced it. Videos are useful explanations, while traces and measured predicates determine outcomes. Structural and thermal studies need solver diagnostics and field artifacts instead of robot-camera recordings.

Failures discovered through targeted search demonstrate counterexamples within the model. They do not directly establish population failure rates. A reduced case is evidence that fewer or smaller declared changes preserve a witness under the performed checks; it is not automatically the unique root cause. Fresh confirmation and reruns strengthen reproducibility, while physical comparison addresses a different question: whether the model matches relevant hardware behavior.

## Product delivery phases

These phases describe implementation milestones. They are not customer lifecycle statuses or calendar promises. A later phase begins when its dependencies and acceptance criteria are satisfied; some research can proceed in parallel.

| Phase | Deliverable | Acceptance criteria and dependency |
|---|---|---|
| P0 Project preparation | The new entry-stage, analysis, asset, parameter, test-plan, readiness, and export foundation. | Records persist; revision conflicts are explicit; invalid inputs are rejected; all execution claims remain gated; existing campaigns remain usable. |
| P1 Qualified known robot | Qualify the fixed LIBERO integration on the target PC, then implement one coherent hand experiment. | Reviewed reference behavior, stable resets, verified observation/action mappings, bounded variations, correct error classification, and complete reproducible evidence. A hand requires its own qualified adapter and behavior. |
| P2 Supported import readiness | A bounded model-package format, dependency validation, reviewable previews, and controller integration. | A documented supported package imports reproducibly; broken packages produce actionable errors; units, frames, geometry, and physical assumptions can be reviewed; code runs only in the intended isolation boundary. |
| P3 Multi-test and regression | Suites, reusable experiment snapshots, model/controller revisions, and comparison reports. | Per-test budgets and outcomes remain distinct; interruptions recover correctly; baseline identities cannot drift; repeated comparisons use declared policies; pilots can retest a revision. |
| P4 Physical calibration | Explicit log schemas, fitting selected parameters, held-out validation, and calibration revisions. | Known reference datasets expose unit/timing errors; fitting and validation data stay separate; residuals and non-identifiability are visible; promoted calibration triggers applicable checks. |
| P5 Structural studies | One bounded structural study class and an isolated solver adapter. | Reference solutions, mesh and boundary checks, convergence handling, provenance, field exports, and engineering review of the supported interpretation. Requires a validated meshing pipeline. |
| P6 Thermal studies | One bounded thermal study class with documented heat inputs and boundaries. | Reference heat-transfer problems, energy/convergence checks as applicable, transient checks if supported, reproducible exports, and validation of assumptions. Coupled multiphysics remains a separate decision. |

Each phase should include an explicit support matrix: accepted files, controller interfaces, mechanisms, variable types, validated platforms, and known exclusions. “Supported robot” should mean a particular asset and adapter revision with declared evidence. A preparation template alone should retain its different label.

P1 must establish that FailureForge can produce useful, trustworthy robot evidence. P2 and P3 then reduce customer setup and repeated-testing effort. Structural and thermal work should proceed only when customer demand and engineering expertise justify the additional engines; welcoming those planning use cases now does not require pretending their solvers are complete.

## Customer validation and decisions still open

The proposed paths are informed hypotheses. Research on mobile-robot simulation identifies setup and environment preparation as barriers, but that evidence does not prove demand across all hardware teams. Use it to guide interviews rather than as a market-size estimate. [Research on simulation-based robot testing](https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2024.1363281/full).

Begin with approximately 8 to 12 exploratory interviews and 2 to 3 assisted pilots, adjusting the sample as patterns emerge. Ask teams to show actual artifacts and their last expensive failure: CAD, robot descriptions, controller packaging, reference tasks, logs, and repeated test procedures. Record what they can share, what they trust, and where preparation work occurs today.

The first pilot should preferably bring a working simulated task. A second can use a supported robot with a custom controller. A third can test the CAD-to-model preparation burden. Measure time to the first valid reference, engineering assistance required, time to reproduce a useful failure, effort to test a revision, and whether the team returns with another revision. Do not reward raw failure count when most findings are setup mistakes or irrelevant conditions.

Decisions that need pilot evidence include the initial simulator, strongest robot/task family, acceptable packaging method, useful variation dimensions, calibration demand, local versus private deployment, and whether structural or thermal customers overlap with the robotics users. There is currently no justified promise that every design can be imported automatically or that every engineering discipline belongs in the first executable release.

The product can nevertheless provide a coherent experience now: meet users at their actual development stage, preserve the information they have, explain what the chosen test still needs, and promote them into execution only when a supported experiment is genuinely ready.
