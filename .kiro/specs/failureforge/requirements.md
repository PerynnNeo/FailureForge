# FailureForge requirements

## Experiment and outcome integrity

- Reject non-finite values, unsupported parameters, overlapping search/confirmation banks, and excessive budgets.
- Run the same two search states for every candidate and only score complete candidate banks.
- Use explicit environment success, stop at success or the declared horizon, and keep integration errors separate.
- Reset exact initial state, policy queues, processors and fresh baseline scene arrays between episodes.

## Investigation

- Support random, scrambled Sobol and declared Sobol/local sampling.
- Preserve the original failing-state set during bounded reduction and verify matched references.
- Confirm a frozen selected case on untouched states without feeding results back into selection.
- Provide fresh paired reruns with explicit extra allowances; preserve disagreements.

## Durable execution and artifacts

- Idempotent requests cannot create duplicate jobs or replenish consumed phase allowances.
- Reserve attempts transactionally, fence completion by lease, retain interrupted attempt costs.
- Publish validated immutable artifacts; incomplete or orphan artifacts remain invisible.
- A clean reader verifies a portable case without loading a model or executable serialized data.

## Interface

- Show actual worker state and measured progress.
- Label synthetic diagnostics everywhere and leave unavailable robot recordings empty.
- Synchronize recorded evidence by control timestamps and retain final frames/outcomes.
- Support keyboard operation, reduced motion, clear text labels and readable measurements.
