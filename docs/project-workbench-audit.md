# Saved project evidence audit

On November 19, 2026, the local workbench held five projects with 44 completed runs. Each run's evidence bundle was exported and verified, including its manifest, saved inputs, solver result, project revision and referenced assets. A fresh solver process then executed each archived definition. **All 44 executions reproduced the exact saved result.** The runtime identity also matched for 23 runs. The other 21 reproduced the numerical results with a different recorded runtime fingerprint. The receipt identifies each run and its outcome. [Audit receipt](../output/verification/project-workbench-audit.json)

| Project | Recorded runs | What the evidence supports |
| --- | ---: | --- |
| Packaging lift | 22 | Two nine-condition matrices each recorded seven passes and two hold failures. With a 0.5 kg parcel and 2 N head force, the lift reached its arrival tolerance, then peaked at 13.949 mm hold error against a 10 mm limit. The model covers a secured payload and prescribed head force. Two other runs used the reference hand. |
| OpenManipulator-X | 12 | Two joint-response fits reproduced the held-out RMSE of 0.002844 rad against a 0.02 rad limit. The five-condition prescribed base-joint sweep recorded two passes and three failures. The project's uploaded URDF identifies its kinematic model. Two other runs used the reference hand. |
| Two-finger hand | 1 | Both joints reached their targets within 0.01 rad in the fixed-palm, contact-free tracking task. This run measures finger closure. A grasp or payload-retention conclusion would require an object/contact test. |
| Thermal rod | 6 | Five heat-generation settings yielded peaks from 300 K to 320 K. Four met the 315 K limit. The sixth run inspected component geometry and carried no thermal pass rule. The fields describe steady state. |
| Cantilever fixture | 3 | At 5 N, increasing section height from 10 mm to 12 mm reduced modeled tip deflection from 0.1143 mm to 0.0661 mm, bringing it within the 0.10 mm limit. The 12 mm section exceeded that limit at 10 N. |

## What changed after inspection

Four past robot-motion runs in the lift and OpenManipulator projects had selected the built-in two-finger hand. Their evidence verifies the reference hand's motion. The replay identifies the model, and the prototype's replay browser gives its own results priority. The run editor now requires an explicit model choice when starting articulated motion for a different prototype. Loaded historical inputs retain their model.

A project holds the model, revisions and recorded runs. A project campaign groups several cases against a saved revision. Its results page shows which conditions passed, failed, lacked an acceptance limit or could not be assessed. Selecting a row reuses the project's recorded run and evidence hash. Existing matrices, sweeps and multi-run suites are indexed automatically. The bowl-placement policy benchmark remains available through **New bowl benchmark**.

Both camera videos were generated and checked for all 44 saved project runs. The renderer reconstructs articulated poses using the verified URDF and recorded joint samples. The OpenManipulator model uses its manufacturer's STL surfaces. The lift follows simulated carriage height and head load on an illustrative fixture. Beam and thermal replays inspect static results, calibration replays show measured samples and CAD replays show surfaces. The policy benchmark captured its main and wrist camera footage during execution. Of the five projects, the OpenManipulator joint-response study also contains measured hardware validation.
