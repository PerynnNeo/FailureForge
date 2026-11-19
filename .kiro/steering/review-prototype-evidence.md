---
inclusion: manual
---

# Review prototype evidence

Use this review when a change adds a modeled input, an acceptance rule or a hardware comparison. Trace one case from its saved project revision through the solver, the coverage report and the run-specific replay.

- Check the solver actually consumes each exposed input. Identify its unit, bounds, the physical assumption behind it and an independently calculable result. Compare a prior input payload with the previous implementation when a new field can be omitted.
- Try a single changed physical input, two inputs that move together, a queued or invalid run, and a site requirement the model cannot represent. Check which cells have observed evidence. Keep qualification errors distinct from an observed physical failure.
- For a hardware trial, inspect the source CSV, trial settings, instrument uncertainty and both evidence hashes. Exercise an interval that straddles the limit and a trial at a different operating point.
- Run the relevant cases in `tests/test_campaign_coverage.py`, `tests/test_crossed_inputs.py`, `tests/test_hardware_trials.py` and `tests/test_project_replay_pair.py`. For a solver change, also run its analytical fixtures in `tests/test_engineering.py`. Report one counterexample with inputs and expected outcome if the evidence supports it.
