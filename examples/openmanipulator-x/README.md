# OpenManipulator-X physical joint-response study

FailureForge fitted a **46.69 ms** first-order time constant for joint 1 of the published OpenManipulator-X follower. On a separate physical repetition of the same sweep, the model predicted the joint position with **0.002844 rad RMSE** (0.163°). The study's preselected limit was 0.02 rad. The measurements came from the Neural Actuation Dataset collected by Dou and colleagues. [Pinned dataset card](https://huggingface.co/datasets/frankzydou/NAD/blob/ac4e634128c8e1d92ddaf023339c374d4e5863f9/README.md)

| Phase | Trial | Samples | Recorded interval | Position RMSE |
| --- | --- | ---: | --- | ---: |
| Fit | `train/001.csv` | 2,056 | 0.0135–35.2274 s | 0.002234 rad |
| Held-out evaluation | `test/001.csv` | 2,529 | 0.0073–43.2297 s | 0.002844 rad |

The condition, split, joint, fit bounds and threshold were chosen before examining either trajectory. Both trials are from `force_unlabeled/joint_sweep_motor11`. For every sample the importer copies the original `timestamp`, `goal_pos1` and `pos1` cells to `time_s`, `command_rad` and `position_rad`. It preserves the recorded clock intervals and checks that timestamps increase. The author-provided train/test split supplies a separate physical repetition of the task. [Original files, hashes and study settings](provenance.json)

The first-order response holds each recorded command until the next timestamp. Each trial starts at its first measured position. The fit minimizes mean squared training error over a bounded time constant of 0.005–5.0 s. Once initialized, validation predictions evolve from the command history alone. Error statistics exclude the initialized first sample. The result characterizes this joint and operating condition. Transfer to a different arm, task, load or trajectory requires additional measurements.

The same project also executed the manufacturer's unmodified URDF in prescribed-motion mode. A 0.35 rad move of `joint1` and 0.005 m move of `gripper_left_joint` over 2 s produced **0.09541 m** of computed end-effector displacement. The right gripper followed its declared mimic joint. The adapter checked position and velocity limits at 101 trajectory samples. This is a kinematic calculation on the published model, separate from the physical telemetry fit. Mesh geometry and contact are outside that calculation. The hardware publisher provides no individual serial number or mechanical-revision match to the manufacturer URDF. [Manufacturer model](https://github.com/ROBOTIS-GIT/open_manipulator/blob/bc555a9c41ebd7493dc945ddabc43fc649681b62/open_manipulator_description/urdf/open_manipulator_x/open_manipulator_x.urdf)

## Bounded speed sweep on the manufacturer model

Five additional runs varied only the base-joint target over a fixed 0.05 s prescribed motion. The source URDF specifies a 4.8 rad/s velocity limit. The gripper target remained 0.005 m. All five runs completed and retained their trajectories. The nearest tested failing target to the 0.12 rad reference was **0.25 rad**, which required 5.0 rad/s. These calculated speeds describe the requested trajectories. The physical arm was not commanded during this sweep. [Saved sweep results](http://127.0.0.1:8000/api/projects/project_b91d43c26de543c5ac188d2918650e3e/sweeps/suite_8b695361add14451bd3f0f23abb7cf5a)

| Target (rad) | Peak base-joint speed (rad/s) | Limit check |
| ---: | ---: | --- |
| 0.00 | 0.0 | Passed |
| 0.12 | 2.4 | Passed, reference |
| 0.25 | 5.0 | Failed |
| 0.35 | 7.0 | Failed |
| 0.55 | 11.0 | Failed |

## Reproduce

```sh
python scripts/import_openmanipulator.py
python scripts/import_openmanipulator.py --submit
```

The first command verifies every original file against its pinned SHA-256 and generates the two three-column measurement files. The second uses the local workbench on port 8000, uploads the source records, projected data, licenses, provenance, and original URDF, then runs the calibration, kinematic motion and five-point sweep. Repeating the command against the same project revision reuses its records. Both commands use the Python standard library.

The verified physical run's evidence hash was `3236a4c53e56a1482c8af22d654b970d60324402d72735948f193ddfdefebdca`. The manufacturer-model run's evidence hash was `e294360c5a6859feefbfa9254f2b1c8cb230f9993f3b1c7b44c1bc692dfc541d`. Local run identities also include project and execution metadata. [Live project on the verified workbench](http://127.0.0.1:8000/#/projects/project_b91d43c26de543c5ac188d2918650e3e)

## Attribution

The original and projected trajectory data are distributed under the MIT license. Credit Zhiyang Dou et al., *NeuralActuator: Neural Actuation Modeling for Robot Dynamics and External Force Perception*, Robotics: Science and Systems, 2026. [Authors' project](https://frank-zy-dou.github.io/projects/NeuralActuator/index.html) · [License](LICENSE-NeuralActuator.txt)

The unmodified robot description is distributed by ROBOTIS under Apache-2.0. It references separately distributed manufacturer meshes. The example includes the URDF alone. [ROBOTIS sources](https://github.com/ROBOTIS-GIT/open_manipulator/tree/bc555a9c41ebd7493dc945ddabc43fc649681b62) · [License](LICENSE-ROBOTIS.txt)
