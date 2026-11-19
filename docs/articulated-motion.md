# Articulated motion

The **Articulated motion** analysis checks whether a fixed-base mechanism reaches named joint targets within a declared time, endpoint tolerance, joint limits and speed limits. Project runs retain the model revision, controller identity, sampled trajectory and measured outcome.

## Run the reference hand

In a robot behavior project, choose **Articulated motion** and use its built-in example. This original MIT-licensed hand has two independently actuated fingers. MuJoCo first holds the open hand and then closes it to a known reference pose using torque feedback. Each qualification trial starts from a fresh simulation state and checks joint error. The second check also compares the measured fingertip separation to the geometric prediction. The requested trial starts from another fresh state. All three trials run headless in the solver process with MuJoCo 3.8.1.

The default requested trial closes the knuckles to −0.35 and +0.35 radians over a two-second allowance. The output includes measured joint positions and velocities, actuator torque, fingertip path length, final fingertip separation and the result of each qualification check. This experiment measures joint tracking with an empty hand.

## Run an uploaded model and controller

1. Upload [the vertical slide URDF](../configs/vertical-slide.urdf) as a robot model and [its controller JSON](../configs/vertical-slide-controller.json) as a controller. The original example model describes a 1 kg vertical carriage driven by a prismatic actuator limited to 30 N.
2. Select **Articulated motion**, attach both files, and use `mujoco_pd` mode. Set the named target to `{"lift": 0.15}`, the duration to `2` seconds, the sample count to `101`, and the endpoint tolerance to `0.001` metres.
3. Inspect the initial-pose hold qualification, terminal error, maximum applied force and the time series. The supplied controller compensates for gravity. Its commanded force approaches 9.81 N when it holds the carriage at the target. The fully specified model also permits a check against the analytic trajectory `q(t) = 0.15 [1 − (1 + 5t) exp(−5t)]` metres.

The adapter constructs a new MuJoCo model from the accepted numeric URDF data. The tree can contain up to 65 links, with fixed, bounded revolute and bounded prismatic joints. It supports joint origins and axes, position/speed/effort limits, joint damping and friction, and box/sphere/cylinder collision geometry. Moving links require primitive collision geometry plus an explicit mass and physically admissible centre-of-mass inertia tensor. Attached fixed links with collision geometry also require inertial data. Inertial origins and rotated tensors are supported. Visual meshes remain outside the simulation. Gravity is 9.81 m/s² along negative world z. Contact uses MuJoCo's default friction and filtering.

An optional UTF-8 `joint-pd-v1` JSON controller assigns each movable joint positive position gain `kp`, nonnegative derivative gain `kd`, and a positive effort cap within the model's limit. For revolute joints the gains map radians and radians/second to N·m. For prismatic joints they map metres and metres/second to newtons. Setting `bias_compensation` to true adds MuJoCo's joint-space bias force before applying the actuator cap. Without a controller file, the imported-model adapter computes critical-damping gains from the diagonal joint-space inertia at the starting pose and the requested natural rate `gain_per_s`. Every dynamic result records the applied gains.

## Prescribed motion and kinematic servo

For a URDF with joint limits and geometry still in preparation, choose `prescribed` to interpolate linearly between start and target positions, or `velocity_servo` to track the target with a first-order velocity-limited servo. Both compute forward kinematics. Supplied positions and velocities use radians for revolute joints and metres for prismatic joints. Unspecified initial positions default to zero. Uncommanded joints hold their starting positions. Select the measured tip link explicitly for a branching uploaded model.

The endpoint tolerance applies to each joint in its own units. Kinematic runs evaluate the requested motion without contact or actuator dynamics. A valid run can fail its endpoint or speed criteria. Unsupported models and invalid joint maps produce a setup error.

For a calibrated rotational joint, select `velocity_servo`, command that joint alone, and bind `time_constant_s` to its measured project parameter. Omit `gain_per_s` when supplying the time constant. For a step from zero to a target of 0.2 radians and a time constant of 0.1 seconds, the unsaturated prediction at 0.1 seconds is 0.1264 radians. The solver uses gain `1 / time_constant_s` and enforces the URDF speed limit if the requested motion initially exceeds it. Other independent joints hold their initial positions. The result records the target joint, time constant, and effective gain. Use measurements for the same mechanism, joint and operating conditions as the planned check.

The kinematic adapter honors URDF mimic joints with affine multiplier and offset, including dependent chains. Command the independent joint. The follower trajectory is checked against its own limits. The dynamic adapter accepts independent joints. The [OpenManipulator-X example](../examples/openmanipulator-x/README.md) runs the manufacturer's original model with its coupled gripper and includes separate published physical measurement logs.
