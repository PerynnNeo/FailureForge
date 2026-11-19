# Build status

Implemented on 19 November 2026 on the development laptop:

- Bounded Pydantic experiment contracts and versioned JSON identities.
- SQLite queue, idempotency, campaign allowances, leases, cancellation, explicit interrupted-job resume and backup support.
- Random, scrambled Sobol and Sobol/local search with persisted proposals.
- Failure-preserving finite reduction, untouched-state confirmation and explicit paired reruns.
- Immutable episode artifacts, checksums, safe portable exports and a clean-reader validation command.
- FastAPI endpoints, CLI and a React/TypeScript workbench.
- An explicitly synthetic mathematical runner for application testing.
- A source-informed real LIBERO/SmolVLA adapter, frozen-runtime bootstrap, target-host qualification and a persistent subprocess watchdog.

The real adapter remains **unexecuted on the target GPU**. No baseline competence, renderer compatibility, failure discovery, robot repeatability, throughput, or real case recording is claimed. The synthetic suite validates application logic only.

## Verified locally

Final verification on 19 November 2026:

- Python suite: **132 passed, 2 GPU-only tests skipped**, in 139.82 seconds. The sole warning is an upstream Starlette/AnyIO deprecation notice.
- Frontend: **5 tests passed**, generated OpenAPI request types refreshed, and production build passed.
- Dependency check: `pip check` reported no broken requirements.
- Browser: created a 32-candidate synthetic campaign, inspected measured results and traces, executed reduction, confirmation and fresh rerun, and checked consumed-action disabling and original/held-out/rerun evidence selection.
- Export: the browser-created case's **1,168-file** bundle passed the standalone reader in a separate process. A subsequent `rerun-bundle` in a new database succeeded with a fresh two-episode allowance.
- Reliability: tests cover stale leases, cancellation, persisted proposals, bounded retries, actual subprocess timeout termination, valid no-improvement reduction, malformed nested bundles and numerical archive allocation limits.

The local development environment and production UI build are installed in this checkout. Preview processes were stopped after verification. Start with the command in the README; the clearly labeled diagnostic campaign remains in ignored `data/` for inspection. [Preview of the verified interface](workbench-preview.png).

Before the robot backend is usable, run the pinned setup and qualification on the separate RTX 5090 PC, review actual policy camera frames, and pass the runtime identity/evidence gates. Before release, complete actual search, paired inspection, reduction (whether or not it improves), held-out confirmation, fresh rerun and export validation on that host. Include unsuccessful searches and infrastructure errors in the study report.

Public hosting, continuous judge compute, browser-native orbitable 3D, arbitrary models/tasks and saved-action replay are outside this local build. No public site or submission has been published.
