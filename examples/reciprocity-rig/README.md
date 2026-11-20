# Aluminum cantilever teaching rig

Jacob Lee Finley and Mehrdaad Ghorashi built a bench rig with a movable load hanger and dial gauge. Their 2013 paper describes the apparatus, its test procedure and two physical readings. That allows a check of whether FailureForge can discover the operating conditions, run the comparison and reproduce the behavior of this particular device. [Original experiment, section 5 and Table 2](https://peer.asee.org/effective-use-of-an-undergraduate-research-fellowship-for-design-and-manufacture-of-tools-to-assist-in-teaching-strength-of-materials.pdf#page=13)

**Open the recorded pair** on the pilot PC, expand **Compare with reference**, then select **150 mm** for the reference station and **300 mm** for the comparison station. You can also inspect the screenshot and simulator footage directly from this checkout. [Open the local comparison](http://127.0.0.1:8000/#/projects/project_b8ca8096a69441bf908c5aa8368400d9/analysis?batch=suite_8dcb4876ad5949b788c66ff24ede3d36&run=run_fcc9acb9bbc4423f9f5fea1b0595c4f3) · [Station comparison](station-comparison.png) · [Tip-load camera](tip-load.mp4) · [Midpoint-load camera](midpoint-load.mp4)

## Results

FailureForge found the 3.47 N midpoint load. Its generated explanation put the gauge at midspan. The builders read the **tip** for this arrangement. The model's maximum deflection coincides with the tip reading here, which earns one numerical match. The operator had to select the correct stations to reproduce the reciprocal comparison. [Recorded inputs and results](comparison.json) · [Checklist score and candidate inventory](repaired-score.json)

| Where the weight acts | Where the gauge reads | FailureForge | Published bench | Simulation minus bench |
| --- | --- | ---: | ---: | ---: |
| Tip, 300 mm | Midspan, 150 mm | 0.25723 mm | 0.19690 mm | +0.06033 mm |
| Midspan, 150 mm | Tip, 300 mm | 0.25723 mm | 0.20638 mm | +0.05085 mm |

The linear model predicts equal reciprocal readings. The physical readings differ by 0.00948 mm. The source gives no uncertainty estimate, so the significance of that difference is unknown. Neither reading supports a pass/fail verdict for the device. The two exported bundles reproduced their complete solver results with networking disabled. The five-second camera views reconstruct each static deformation from saved field data and magnify it for visibility. [Bench observations](bench-readings.json) · [Offline verification](offline-verification.json) · [Tip-load bundle](tip-load.zip) · [Midpoint-load bundle](midpoint-load.zip)

| Frozen procedure item | What FailureForge found after the fixes |
| --- | --- |
| Midpoint load, read at tip | Numerically covered. It applied the correct load and returned the tip value as the beam maximum. Its suggested gauge location was wrong. |
| Tip load, read at midpoint, compare reciprocal readings | Related idea only. The tip load came from the intake. The generator mentioned a midpoint gauge under the other loading condition. The operator selected the two actual stations. |
| Keep the probe centered and perpendicular | Missed. A question about beam orientation did not identify probe alignment. |
| Set initial probe compression | Missed. The beam solver has no model of the gauge mechanism. |

The identical brief produced seven suggestions in the corrected build. Six ran without an invented acceptance limit. The seventh, about permanent deformation, remained unsupported by the linear elastic solver. Uniform and distributed load cases explore other mathematical loads. The documented fixture has a single hanger, so those cases need additional hardware assumptions before they can be treated as use cases for this rig. The generator also described a dial gauge measuring stress. The gauge measures displacement. The interface now shows the AI hypothesis separately from the recorded inputs and outputs. [Generated suggestions](repaired-batch.json) · [Execution receipts](repaired-results.json) · [Review judgments](repaired-review.json)

## What the operator started with

The ordinary engineering inputs were a description of the apparatus, its material, free span, load and bending inertia. The authors did not publish CAD, measured section dimensions, a specimen-specific elastic modulus, a pass limit or measurement uncertainty for this rig. The published protocol predates FailureForge. An automated browser operated the workbench, and a separate offline review graded its output against the four published procedure items. This was a retrospective study of a public experiment. The builders did not participate in this software trial.

| Input | Value used | Basis |
| --- | --- | --- |
| Free span | 300 mm | Table 2 |
| Reference load | 3.47 N, at the free end | Table 2. The surrounding text gives 3.48 N. The same table value was used throughout. |
| Bending inertia | 542 mm⁴ | Table 2 labels this column “pm⁴”. We interpreted 542 as 542 × 10⁻¹² m⁴, consistent with the published calculated displacement. |
| Section | Equivalent square, 8.98039 mm per side | The rectangular solver needs width and depth. The operator chose the fourth root of 12 times the published inertia for each side. This preserves bending stiffness. The study makes no inference about the specimen's surface stress. |
| Elastic modulus | 70 GPa | A nominal aluminum value consistent with the authors' theoretical result. It was not fitted to either bench reading. |
| Pass limit | Unspecified | The experiment measures displacement. There is no published acceptance threshold. |

## Repeat through the workbench

1. Create a project with **I have a physical prototype → Strength & deformation**. Enter the name, goal and success criteria from [the intake](intake.json).
2. Open **Discover scenarios → Import a reference model from JSON**. Choose [the translated beam definition](reference.json), then **Import and run reference**. This translation is a manual engineering step.
3. When the reference is selected, enter only the operating question from the intake and choose **Generate and run test cases**. Keep the checklist and bench readings out of this step. A fresh local model generation may produce different suggestions.
4. Inspect the load locations and saved solver inputs before comparing the two cases. The midpoint load goes at 150 mm. For the source comparison, read the **tip-loaded reference at 150 mm** and the **midpoint-loaded comparison at 300 mm**. In **Compare measurement stations**, choose each station separately. Open **Compare a bench reading** under each station and enter the corresponding [published readings](bench-readings.json). Bench entries are local to the open view.
5. Use **Download proposals (JSON)** and **Download results (JSON)** in the saved generation to audit a new attempt. The [offline evaluation guide](../../docs/prototype-pilot-evaluation.md) explains how to freeze and grade a different prototype's checklist.

## Original software

The checklist was locked before creating the project. The first generation stopped at the model's output limit. An identical retry suggested moving the hanger to the clamp and executed zero scenarios. One suggestion was related to load location. None of the four published checks was reproduced. The registry required an acceptance limit to compile a beam scenario, which excluded this measurement-only experiment. [Checklist](checklist.json) · [Freeze receipt](lock.json) · [First attempt](initial-batch.json) · [Original retry](cold-batch.json) · [Original results](cold-results.json) · [Checklist review](cold-score.json)

The operator supplied the missing model geometry and modulus, entered the brief and reference through the UI, retried the original failed generation and supplied the published gauge readings after discovery. We added measurement-only beam scenarios, a bounded retry for truncated model output, side-by-side measurement stations for beam and rod fields, and UI export of discovery evidence. The corrected batch completed on its first inference call. Its cases draw on a finite registry of possible solver operations. The protocol and bench readings stayed outside the generator.
