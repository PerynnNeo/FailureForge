# FailureForge project constraints

The initial specifications were prepared with Codex. Kiro Agent subsequently implemented the campaign condition comparison and wrote tests for changing conditions and synchronized replay. Local review corrected the interpretation of solver thresholds and playback of unequal recordings. [Implementation and review history](https://github.com/PerynnNeo/FailureForge/pull/1)

Kiro also reviewed the operating-condition coverage and hardware-comparison algorithms. Its review proposed checking equivalent units at an inclusive limit, a verdict that changes only because the threshold changed, and a six-cell campaign with two blocked cases. These regressions are exercised in `tests/test_hardware_trials.py` and `tests/test_campaign_coverage.py`. The on-demand `review-prototype-evidence` steering document describes how to repeat this review as the adapters change.

Keep contracts, queue logic and artifact inspection importable without CUDA or model weights. The real execution target is a separate RTX 5090 PC under the pinned Linux runtime. Laptop diagnostics must remain visibly synthetic.

The outcome authority is the environment's task predicate. Infrastructure errors are not robot failures. Preserve exact initial-state identities, seeds, processor/model revisions, coordinate frames, units, and action horizon. Camera displacement is in the supported camera's parent frame; lighting modifies simulator arrays. Never fabricate robot recordings or measured trial points.

Run fast tests deliberately using `python -m pytest --basetemp=tmp/pytest-local`. GPU qualification is explicit and must never run on every file save. Preserve immutable completed evidence and shared campaign budgets. All normal code changes should maintain the verified synthetic workflow and web build.
