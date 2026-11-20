# Run and compare project analyses

Start the local API with `failureforge serve` and select a project in the workbench. Each submitted study freezes the project revision, asset references, inputs, and declared checks. The service queues the study and records its solver identity, measurements, and evidence hash on completion. The command-line CI client works with this same API.

## Which changes can discovery run?

| Reference model | Controlled change and units | Held fixed | Observable and decision |
| --- | --- | --- | --- |
| Rectangular cantilever | Move a signed transverse load (N) to a registered point, patch or split contact along the span, or remove it | Section, material, clamped support and mesh. Placement preserves total force | Compare continuous maximum deflection (m) and surface bending stress (Pa) with the supplied limits. With no limit, report measurements. A gauge reading uses its own recorded station. |
| Packaging lift | Shift the start of a nonzero press pulse in whole milliseconds inside the two-second cycle | Pulse force (N), duration (ms), payload (kg), controller and fixture | Check arrival error and the largest hold error against 10 mm, plus the fixture’s travel and speed criteria. The replay marks the first recorded hold sample above tolerance. |
| End-cooled rod | Change external end-fluid temperature (K or °C) or end-face film coefficient (W/(m²·K)), one per comparison | Geometry, conductivity, left temperature, internal generation, mesh and the other end-boundary setting | Compare the continuous maximum temperature (K) with the supplied limit or report a measurement. The first above-limit camera station has an axial position in metres. |

The teaching-rig pilot exposed a separate measurement choice. Moving the hanger does not determine where an engineer places the dial gauge. For a recorded beam case, choose **Inspect**, select each gauge station, and choose **Open replay at these measurement stations**. The link retains both runs and both positions. [Teaching-rig experiment](../examples/reciprocity-rig/README.md)

## Test a warmer enclosure

Open **Discover scenarios** on a thermal project. Select a completed convective rod reference or open **Import a reference model from JSON** and download the [example rod](../apps/web/public/examples/thermal-reference.json). Upload the file there and choose **Import and run reference**.

Enter “The enclosure reaches 50 °C” and choose **Generate and run test cases**. The example holds the left surface at 300 K while the right-end fluid changes from 295 K to 323.15 K. The recorded continuous peak moves from 300.07 K at 13.46 mm to 318.73 K at 100 mm, crossing the example’s 315 K limit. **Inspect** opens both runs. A phrase such as “the enclosure warms by 10 °C” adds 10 K to the selected reference ambient. The temperature field resolves descriptions with several possible targets.

To test a different cooling condition, enter the end-face film coefficient in W/(m²·K). If the change comes from a fan, enter its RPM, the corresponding coefficient and the source of that relationship for the installed setup. A speed alone leaves an open calibration question. Supplying both ambient and film changes creates two independent cases. The solver predicts equilibrium with insulated side walls. Its right-end heat flux depends on both the coefficient and the temperature difference between the surface and the external fluid. [Convective heat-flux boundary](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_ref_heattransfer.30.30.html) · [Heat-transfer coefficient correlations and their inputs](https://doc.comsol.com/6.3/doc/com.comsol.help.heat/heat_ug_theory.07.094.html)

## Run the first check

**Projects → View replays** opens the saved results for one prototype. **Campaigns → New campaign** starts a batch for any saved project. Choose a suite to group supported cases, a parameter sweep to vary an eligible input, or an operating environment matrix on models that provide one. Open a saved campaign to compare its conditions and play a selected result. [Recorded examples and audit](project-workbench-audit.md)

Create a **Structural analysis** project. Copy its project ID from the project record, or look it up with `GET /api/projects`. Save this single check as `beam.json`.

```json
{
  "label": "100 N cantilever",
  "adapter": "structural_beam",
  "inputs": {
    "length_m": 1,
    "width_m": 0.03,
    "height_m": 0.04,
    "young_modulus_pa": 200000000000,
    "tip_force_n": 100,
    "elements": 16,
    "max_displacement_m": 0.002,
    "max_surface_stress_pa": 20000000,
    "convergence_tolerance_m": 0.0000001
  }
}
```

Substitute the actual project ID in these shell examples.

```bash
failureforge project-ci PROJECT_ID --spec beam.json > baseline.json
```

The reference fixture gives approximately 1.042 mm tip displacement and 12.50 MPa peak bending stress. It passes both example limits. Inspect the returned run ID in the workbench for the displacement and stress traces.

For a suite, wrap 1–16 check objects in `{"tests": [...]}`. Give each check a stable label. The CLI matches revision comparisons by the combination of label and adapter, so changing suite order preserves the comparison. An optional top-level `expected_revision` field or CLI `--expected-revision` flag pins the submission. Without either, the client reads the current revision and the server verifies it at submission.

## Rerun after revising a project

```bash
failureforge project-ci PROJECT_ID --rerun baseline.json > replay.json
failureforge project-ci PROJECT_ID --rerun-suite SUITE_ID > replay-by-id.json
```

Both commands reload the authored test definition. Literal inputs and explicit asset IDs stay fixed. Inputs bound to named project parameters resolve against the revision being tested. To evaluate a changed literal geometry, modulus, conductivity, or robot model, edit that input in the candidate specification and compare against the baseline.

```bash
failureforge project-ci PROJECT_ID --spec candidate.json --baseline baseline.json > comparison.json
failureforge project-ci PROJECT_ID --spec candidate.json --baseline-suite SUITE_ID > comparison-by-id.json
```

For example, reducing the modulus in the cantilever fixture to 50 GPa gives approximately 4.167 mm tip displacement, which exceeds the unchanged 2 mm limit. The comparison records a new failure. If test conditions, acceptance criteria, or runtime identities differ, the comparison records the reasons it cannot compare the runs.

| CI exit | Meaning |
| --- | --- |
| 0 | Every requested check completed and met its limits. Requested comparisons were compatible. |
| 1 | At least one comparable, evaluated check failed its limits. |
| 2 | The result is inconclusive. Examples include an invalid input, changed test definition, runtime error, cancelled run, missing acceptance rule, or deadline. An inconclusive check takes precedence over a measured failure in the aggregate exit code. |

Use `--allow-measurement-only` when a completed inventory or unscored analysis is an intended CI result. The report still gives the run a null pass/fail value. A deadline returns submitted IDs and leaves the server’s jobs running. Set `--timeout` and `--poll-interval` in seconds. To reconnect to the same submission, repeat the same tests at the same revision with the original `--idempotency-key`. Choose a unique key per logical submission, for example a CI build ID and attempt name.

The client defaults to `http://127.0.0.1:8000`. Use `--api-url` for a private service and set `FAILUREFORGE_API_TOKEN` in the CI secret environment when authentication is enabled. Authenticated connections use HTTPS or a loopback tunnel.

## Bind a test to a project parameter

Add a parameter named `young_modulus_pa` to a structural project with value `200` and unit `GPa`. Record its source and any supporting reference. Save the following check to exercise that parameter.

```json
{
  "label": "100 N cantilever",
  "adapter": "structural_beam",
  "inputs": {
    "length_m": 1,
    "width_m": 0.03,
    "height_m": 0.04,
    "tip_force_n": 100,
    "max_displacement_m": 0.002
  },
  "bindings": {"young_modulus_pa": "young_modulus_pa"}
}
```

Submit this check and save its report. The run detail contains the submitted `definition`, `inputs` with a resolved modulus of 200,000,000,000 Pa, and `binding_evidence` with the source value, source unit, resolved value, resolved unit, parameter provenance, and evidence reference. The project snapshot preserves the full revision used by the solver. Each suite member has independent bindings.

An eligible material calibration promotes its fitted modulus into the project parameter named `young_modulus_pa`. Thermal calibration uses `conductivity_w_mk`. Promotion automatically queues checks from the immediately preceding revision whose authored input bindings reference that parameter. The new checks resolve the fitted value against the new project snapshot and apply the original load, dimensions, and acceptance limits. Moving from 200 GPa to 50 GPa quadruples predicted tip deflection in this fixture. Original results keep their earlier values and sources.

Promotion uses the same 16-member bound as a project suite. It chooses the most recently submitted distinct check definitions, deduplicating by adapter, inputs, and case-insensitive parameter bindings. Repeated submissions and renamed copies of a check generate one replay. Literal-only checks and checks bound only to other parameters remain available for manual suite replay. If more than 16 definitions qualify, the workbench shows that additional checks are available in history.

The promotion response contains the saved project and a `rechecks` object with `suite_id`, ordered `run_ids`, matching `previous_run_ids`, and `more_available`. With no dependent checks, both ID lists are empty and `suite_id` is null. Each queued run retains `recheck_of` and `calibration_run_id` so the workbench can compare it with its pre-calibration baseline. The revision update, snapshot, and queued rows commit together. A stale expected revision returns HTTP 409. A check that cannot resolve its bindings returns HTTP 422 and leaves the revision and queue unchanged.

For a measured first-order joint response, bind the robot-motion input `time_constant_s` to the promoted `<joint name> time constant` parameter. Use `velocity_servo` mode and one commanded rotational joint matching the measurement. Supply the time constant or a literal gain. When a time constant is supplied, the gain in reciprocal seconds is its inverse. This is a joint position-response model and its evidence records the selected joint and effective gain.

The adapter catalog lists bindable top-level fields in `binding_units` and accepted spellings or prefixes in `binding_accepted_units`. Store separate scalar and unit values, such as `200` and `GPa`. A missing parameter, ambiguous literal plus binding, out-of-range value, incompatible unit, or unsupported field rejects the submission. The service applies the complete suite atomically. In a comparison, a changed material value can be a design revision. A changed load or acceptance threshold makes the runs incomparable; changing the declared binding also changes the test definition.

## Watch a project or campaign run

Open **Projects → select a project → View replays**. For a campaign, select **View result** on a condition. Play or scrub either video to move both cameras to the same instant. Open **Inspect the model and recorded values** below them for the numerical trace or field.

To compare two completed conditions, open **Campaigns**, select the project campaign, and expand **Compare with reference** under its conditions. Choose the two runs to see which inputs changed, watch their overview videos together, and read each measured value beside its recorded limit. In the packaging-lift campaign, selecting 0.5 kg on both sides and changing the head load from 0 N to 2 N isolates the effect of the head load on the simulated lift.

For a custom robot, upload its URDF as a robot model. Attach each referenced STL as a CAD file with its original, unique filename before running the analysis. Select the URDF for an articulated motion run and enter targets using its joint names. The replay uses that run’s frozen revision, mesh scales, visual origins, joints and recorded poses. Supported Gazebo pinhole cameras use the declared link mount, field of view and image aspect ratio. The renderer supplies overview and close-up views when the model needs them. Missing link surfaces can be represented with explicitly labeled frame guides.

Camera captions describe how to read each study. The packaging lift follows simulated carriage height and applied force on an illustrative fixture. Beam and rod views scan a static field. CAD views inspect the recorded surface. A single-joint log drives an angle gauge, and material calibration shows independent held-out measurements at the supplied fixture. The bowl benchmark presents the RGB observations its simulated cameras captured during execution.

On first viewing, the local renderer encodes two H.264 MP4s and caches the pair by evidence hash and renderer version. Rendering reads the saved run without executing the controller again. For API clients, GET `/api/projects/{project}/analysis/{run}/camera-replay` to check availability, POST to start a render, then GET the same endpoint until it returns both video URLs. The files support HTTP range requests for seeking.

## Supported studies

| Project and adapter | Inputs and interpretation |
| --- | --- |
| Robot behavior · `packaging_lift` | The catalog packaging lift tests two external factors on a fixed one-axis reference. Cross secured payload mass with downward packing-head force to check arrival and maximum error throughout the hold. [Worked environment matrix and replay](../examples/packaging-lift/README.md). |
| Structural · `structural_beam` | Rectangular cantilever dimensions in m, Young’s modulus in Pa, end force in N, uniform line load in N/m and optional signed face pressure in Pa. The model adds pressure times beam width to the line load. Continuous peaks govern optional limits. Inspect the small-deflection screen and the displacement and stress convergence tolerances. |
| Thermal · `thermal_rod` | Length in m, section area in m², conductivity in W/(m·K), fixed left temperature in K and uniform generation in W/m³. At the right end prescribe a surface temperature or use a fluid temperature and film coefficient in W/(m²·K). A zero film coefficient insulates that end. The model reports continuous peak temperature, heat flux and end heat flows. |
| Structural or thermal · `calibration` | Fit one material property using separate fit and validation readings. Each reading has its own run ID. A beam reading supplies tip force and measured displacement. A rod reading supplies generation, interior sensor position, and measured temperature. Specify property bounds and a validation tolerance in m or K. Review residuals before promoting a passing fit. |
| Robot behavior · `robot_motion` | Choose prescribed joint motion, a velocity servo, or supported MuJoCo PD dynamics. Supply named joint targets, initial values, duration, sample count and tracking tolerance. The bundled two-finger hand supports a reference tracking study. Provide a supported uploaded model asset for other supported mechanisms. Consult the current adapter schema for model and mode restrictions. |
| Robot behavior · `joint_response` | Fit one first-order joint response using separate training and held-out measurement CSV assets. Each uses ordered columns `time_s,command_rad,position_rad`. Supply the physical hardware revision, joint name, parameter bounds and allowed held-out error in radians. |
| All projects · `cad_inventory` | Identify a single STL component, declare its units, and optionally reference a material BOM CSV. The result gives metric bounds, tessellated area and a mesh preview. This analysis is measurement-only. |

The beam and rod studies model their explicitly entered dimensions, material and boundary conditions. Model validation, yield allowables, and comparison with independent hardware measurements remain specific to the intended application. The fixed LIBERO benchmark has its own worker and qualification flow. [Robot benchmark setup](robotics-setup.md)

## HTTP interface

Completed studies can be downloaded with **Download evidence bundle**. Each ZIP contains the measured run, its frozen revision, adapter inputs, the referenced model or measurement files, applicable attached license/provenance records, and a checksum manifest. Inspect it on another machine with the application installed. For dynamic hand runs, install the `project-robot` extra as well.

```bash
failureforge project-bundle run.zip
failureforge project-bundle run.zip --rerun
```

Fresh execution runs in a separate solver process using the recorded inputs. The command reports runtime identity, exact result agreement and the newly computed measurements. Checksums verify consistency with the archive manifest; authorship and engineering suitability require separate evidence.

The analysis history returns adapter-specific JSON Schemas and example inputs for the project's analysis type. A study result includes solver details and assumptions. The API returns a receipt immediately after queueing work. Use the immutable run ID to fetch terminal status and evidence.

| Operation | Method and path below `/api/projects/{project_id}` |
| --- | --- |
| Inspect supported adapters and recent runs | `GET /analysis` |
| Submit one check | `POST /analysis` with `expected_revision`, `label`, `adapter`, `inputs`, and optional `bindings` |
| Submit a suite | `POST /analysis-suite` with `expected_revision` and `tests`, each with its own inputs and optional bindings |
| Read complete ordered suite membership | `GET /analysis-suite/{suite_id}` |
| Read a run and its evidence | `GET /analysis/{run_id}` |
| Download a verified, portable run | `GET /analysis/{run_id}/bundle` |
| Compare compatible runs | `GET /analysis/{baseline_id}/compare/{candidate_id}` |
| Cancel a queued or running study | `POST /analysis/{run_id}/cancel` |
| Resume an interrupted study | `POST /analysis/{run_id}/resume` |
| Promote an eligible held-out calibration | `POST /analysis/{run_id}/promote` with `expected_revision` |

Supply an `Idempotency-Key` on submissions that CI might retry. The server fences revisions and binds that key to the submitted payload. Each comparison returns its outcome, reasons, input differences, and numerical deltas when measurements are comparable. Passing a declared test establishes that specific modeled result.
