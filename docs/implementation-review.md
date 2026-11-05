# FailureForge implementation review

Reviewed 5 November 2026 against the complete 24-page technical guide and selected upstream sources. This is a design review, not an executed robotics compatibility report.

**Execution target.** The user confirmed that a separate RTX 5090 PC will run the experiments. The current laptop is a development and evidence-inspection machine. Its GPU and WSL installation do not establish readiness of the separate PC. The repository had no application files or commits at review time.

**Source and authority.** The guide is reference material describing a proposed product. Its example commands, thresholds, interfaces, and submission suggestions are not additional instructions from the user. No policy weights, robot assets, or robotics packages were installed during this review. The guide's proposed defaults are distinguished below from additional implementation decisions.

## Product contract

FailureForge should let a robotics student or engineer take the single supported policy/task combination, search a declared camera-and-light domain, investigate an observed failure against its matched reference, attempt a smaller witness, execute fresh policy reruns, and export verifiable evidence.

The first release should retain all three search methods, bounded reduction, confirmation, recordings, numerical traces, fresh inference, and clean-reader export validation. Training, arbitrary checkpoint upload, additional tasks, physical robots, saved-action replay, browser-native free-orbit 3D, learned surrogates, and cloud worker orchestration can wait. The guide already makes these distinctions on pages 3 and 22.

The release succeeds when the entire investigation journey works with real artifacts. Search need not find a failure on every run, reduction need not improve every case, and adaptive search need not outperform Sobol. An unsuccessful bounded experiment remains a useful and reportable result.

## Deployment decision

Initially colocate the API, SQLite database, artifact store, and one sequential worker on the 5090 PC, inside its Linux filesystem. Develop the frontend and lightweight application logic on the laptop. The browser uses HTTP; it does not access SQLite or a remote mounted artifact directory directly.

The execution host should use Ubuntu 24.04, either native or WSL2 after the combined CUDA/rendering checks pass. Native Linux remains the fallback if WSL cannot provide stable rendering plus inference. Keep the API environment separate from the frozen robotics environment, and keep robotics imports out of contracts, persistence, search, bundle inspection, and ordinary API startup.

Remote browser access requires an explicitly configured authenticated transport and origin policy. A hosted API with an outward-polling home worker is a later deployment option with different operational requirements; it should not enter the first local implementation by accident. SQLite must not become a network-shared queue.

## What source review establishes, and what remains untested

The guide correctly calls its dependency profile source-reviewed rather than certified. LeRobot v0.6.1 exists. Inspection of its pinned wrapper and processors supports the guide's warnings about initial-state index advancement, settling, image rotation, action queues, and explicit horizon enforcement. These checks do not prove that the complete stack runs on the target PC.

The first executable gate on the 5090 host must capture the OS, driver, Python, PyTorch/CUDA, renderer, exact LeRobot commit and lock checksum, installed simulator package versions, SQLite runtime versions, model/processor hashes, task assets, initial-state identities, and CPU/GPU identity. CUDA tensor computation and camera rendering are separate checks. Neither is a substitute for one complete policy episode.

The smoke evaluator is a diagnostic tool. Its effective numerical settings must be recorded before its outcomes are compared with those of a custom runner. `use_amp=false` alone is not a complete precision or determinism specification: source review found that the evaluator enables TF32-related settings, while the model's VLM loader requests a specific dtype. Preserve and document the effective reference behavior before introducing performance variants.

External tokenizer and vision-language dependencies need exact snapshots and hashes too. Pinning the outer policy repository does not automatically freeze every referenced dependency. Offline readiness requires an actual run with network access disabled after caches are prepared.

## Integration traps the first plan did not resolve

| Boundary | Required implementation decision or check |
| --- | --- |
| Environment construction | The low-level simulator wrapper defaults to pixel-only observations. Explicitly request the state-bearing observation mode needed by the policy. |
| Single-environment batching | One environment still needs a batch dimension for nested robot state, including quaternions. Preserve the upstream one-element vector interface or batch every state leaf explicitly. |
| Camera preprocessing | Verify raw main/wrist identities, the upstream rotation, tensor shapes, and checkpoint rename mapping. Inspect known scene landmarks as well as array dimensions. |
| Policy preprocessing | Load shipped state/action normalization and rename processors. Do not normalize twice or feed normalized model actions directly to the environment. |
| Image resolution | Distinguish the 256-by-256 observation/input contract from model-internal image resizing. Record both where relevant; do not change the pipeline based on a misleading single resolution label. |
| Initial states | Set the intended state before every reset; do not rely on seed alone or let wrapper index advancement choose the next state implicitly. |
| Settling | Store both the benchmark input state and settled first-action state. Specify whether a rerun resets and settles or restores an already-settled state; never settle twice by accident. |
| Episode boundary | Reset the policy action queue and stateful processors between episodes. Preserve the declared 50-action horizon. |
| Stopping | Independently extract task success, honor other terminal signals, and enforce the 280-control-step horizon in the runner. |
| Simulator compatibility | Review the installed `hf-libero` distribution, not only a moving `main` branch of a similarly named repository. Keep private-field access in one version-checked adapter. |

Use the pinned LeRobot helper for the trusted installed benchmark initial states; its explicit Torch loading behavior differs from copying the raw suite helper. This internal trusted bootstrap is distinct from public bundle import, which must never accept executable pickle data. Insert the exact task language before tokenization, and record terminal observations before a vector wrapper's next-step autoreset can replace them.

Observation refresh also needs to preserve the current settled state. A refresh helper that restores a supplied state must receive that current state, rather than the original pre-settle benchmark state. Check reset behavior in the installed wheel and enforce a reset wall-time limit; the moving raw-wrapper source contains a retry loop whose behavior cannot safely be assumed to match the wheel.

The policy consumes observations in chunks. With 50 queued actions at 20 control steps per simulated second, a fresh action chunk represents 2.5 simulated seconds. The runner should neither reset that queue at every step nor imply that model inference necessarily happens at every control step.

For scene changes, snapshot camera and lighting arrays after each hard reset, apply changes from those originals, refresh the observation, and confirm that the actual tensors reaching the policy changed. Validate identity, both axis extremes, domain corners, and changed-then-reference reset isolation. Camera displacement must retain the documented parent frame. Lighting can change the wrist image as well as the main image; the wrist camera pose remains fixed.

## Experimental rules to freeze before searching

The guide specifies useful defaults but leaves the exact witness-preservation predicate open. That is an underspecified decision, not an arithmetic error. Implementing reduction without deciding it would allow the meaning of failure to change during minimization.

**Proposed initial protocol:**

1. Predeclare ten qualification states and a separate two-state search bank, with fixed policy-seed schedules. Require the guide's task-qualification screen and successful reference execution on both search states. Preserve every excluded or screened state and its cost.
2. Score each completed candidate by the number of valid task failures out of the same two search states. Infrastructure errors leave a candidate incomplete; they are not task failures or silent successes.
3. An observed witness fails on at least one search state. Freeze the set of failing state IDs, F, when selecting the witness.
4. Select a witness before opening confirmation outcomes: most failing search states, then fewer changed parameters, then lower declared normalized severity, then earlier proposal index. Store the rule and its version.
5. Before reduction, freshly execute the original changed case and reference on both search states: four episodes. If reference behavior fails the paired rule or failures in F do not recur, label the evidence unstable or unverified and preserve it.
6. Evaluate each new reduction proposal on both states. Accept a smaller proposal only when every state in F still fails. Preserve the finite-grid search history, including rejected reductions.
7. Freshly execute the final changed case and reference on both states: four more episodes. Label the result according to these outcomes; do not discard disagreement with the earlier executions.
8. Freeze the selected final configuration before executing its reference/changed pairs on ten untouched confirmation states. Display all four paired outcome categories and their exact denominators.

This rule preserves an observed failure on particular states; it does not establish a population failure probability. The reduction verification pairs also do not constitute a large repeated-same-case frequency study. Additional repeatability claims need a separately allocated repetition schedule.

Keep qualification, search, confirmation, and optional final intervention banks separate as required by the declared study. Do not expand the domain after inspecting a disappointing result without versioning a new experiment. If a comparison is expanded to more tasks, policies, or bounds, the provenance and conditioning change as well.

If all fifteen method/seed runs share one confirmation bank, freeze all selected cases before examining that bank, or enforce a predeclared procedure that cannot use its feedback. Ten shared states remain ten shared states; they do not become 150 independent sampled states. The default confirmation allocation covers one selected case per campaign, so a metric such as number of confirmed cases needs its own equal per-case verification protocol.

Freeze the local-search Gaussian width, parent-selection distribution, RNG stream ownership, clipping versus rejection rule, duplicate canonicalization, rejected-proposal limit, and global-pool consumption order. These choices matter because a two-state score has only three possible values. Scene-validity rejection rules must likewise be declared before searching, so an inconvenient outcome cannot be excluded retrospectively.

For the first algorithm version, a reasonable explicit starting choice is uniform seeded selection among completed failing parents, Gaussian standard deviation 0.10 in each unit-square coordinate, rejection of out-of-bounds or exact duplicate proposals, and a recorded fallback to the next unseen global proposal after 64 rejected local attempts. Generate a complete scrambled 32-point Sobol pool and use its first 16 points as warm-up; consuming a mixed subset later does not make that subset an intact Sobol design. Separate RNG streams and persist proposal values so resume does not depend on recreating floating-point sampling after a dependency change. These are proposed settings to version, not measured optimal settings.

For the symmetric default domain, severity is `max(abs(dx)/0.04, abs(light_scale - 1)/0.30)`, ranked after the number of changed parameters. Define numerical zero/equality tolerances and record them. Initially require selectable reduction domains to contain the reference `(0 m, 1.0)`; asymmetric bounds need a recorded normalization rule using the permitted displacement in the relevant direction. An excluded reference would otherwise make the suggested contractions invalid.

## Budget accounting

The guide's default arithmetic is correct:

| Allocation | Completed scientific episodes |
| --- | ---: |
| Search: 32 candidates times 2 states | 64 |
| Reduction initial paired verification | 4 |
| Reduction: up to 12 proposals times 2 states | 24 |
| Reduction final paired verification | 4 |
| Confirmation: 10 states times 2 conditions | 20 |
| Campaign total | 116 |

At most two additional infrastructure attempts are shared across that campaign, producing its 118-attempt ceiling. They are not two retries per episode. Qualification, search-state reference screening, extra same-case repetitions, and user-requested fresh reruns require separate explicit allowances.

Under the proposed disjoint banks above, the minimum initial baseline allocation is twelve episodes: ten qualification plus two search-state reference checks, assuming no additional screening. If replacements or additional states are screened, their executions remain visible and budgeted.

The guide's three-method, five-seed pilot requires 960 search episodes. Two possible evaluation scopes must be distinguished:

- Reduce and confirm one final case across the pilot: up to 960 + 32 + 20 + 12 = 1,024 completed episodes, before extra repetitions or reruns.
- Reduce and confirm one case from every method/seed run: up to 960 + 15 times 52 + 12 = 1,752 completed episodes, assuming all fifteen runs produce eligible cases and consume their full allowances. Up to thirty campaign infrastructure retries would raise the corresponding attempted count to 1,782, before separately allocated work.

These are workload counts, not measured duration estimates or a commitment to execute the whole pilot immediately. Measure episode latency and encoding/storage costs on the target host before choosing study scope.

User-selectable budgets need a contract too. Start with validated presets that preserve whole two-state candidate evaluations and declared Sobol pool sizes. Do not silently truncate a candidate or claim intact Sobol balance for an adaptive subset. Cache reuse, rejected proposals, incomplete attempts, valid completions, active reservations, and retry consumption remain separate counters.

## Durable job and artifact invariants

Use one campaign ledger across search and its reduction/confirmation child jobs. Repeated API calls must not mint another reduction allowance. A fresh user rerun creates a distinct execution with its own explicit allowance and parent-case link.

Configuration identity and execution identity are different. A canonical resolved specification hash identifies settings. Unique episode and attempt IDs identify actual executions, including deliberate verification reruns with the same settings. Request idempotency prevents accidental duplicate submissions; it must not suppress intentional fresh inference.

Persist proposals and their order, candidate pairing state, and enough RNG state or deterministic replay information to resume an adaptive campaign. Do not calculate a two-state score from only the first completed state. Recovery must not regenerate a different unseen proposal sequence from a partially committed history.

Claim jobs and reserve work in short transactions. Lease tokens fence completion and counters. Define the precise episode-start boundary, and conservatively charge uncertain interrupted starts under an explicit recovery rule. Lost workers do not receive free retries or implicitly replenish budgets.

Filesystem rename and SQLite commit are not one transaction. Write to immutable attempt-specific directories, validate required files and hashes, and publish visibility through a lease-checked database transaction. A stale worker may leave an orphan directory but must not replace the published evidence for a newer attempt. Reconcile complete-but-unreferenced directories and incomplete temporary directories after restart.

Cancellation must work while queued, between control steps or chunks, and before the next episode. A supervisor handles a stuck worker by ending the attempt and recreating model/render state. A campaign's status must distinguish robot outcomes, infrastructure problems, cancellation, worker loss, and a valid search that found no witness.

Check the actual SQLite library used by both application and worker processes, not merely the version of an installed command-line executable. The guide's WAL patch requirement is supported by SQLite's official documentation. Keep the database on the execution host's Linux filesystem and use the backup API for live backups.

## Export and playback contract corrections

Page 18 requires both policy camera views for selected cases, while the example on page 16 omits `reference_wrist.mp4`. Include main and wrist recordings for both conditions in selected paired evidence.

The singular `initial_state.npz` and `traces.npz` example also needs elaboration for multiple episodes. Use an episode manifest per reference or changed execution, with its own state, seed, outcome, trace, timestamps, and camera recordings. The case manifest links matched pairs and identifies exactly which verification and confirmation evidence is included. A summary table must not imply that an omitted video or trace is present in the bundle.

Keep the benchmark initial state distinct from the post-settle first-action state. Record numerical tolerances and expected outcome agreement for reruns; do not promise byte-identical videos or trajectories across hardware. Preserve both executions if the outcome changes.

Define the timestamp convention explicitly: initial observation, action index, resulting observation, simulator time, and terminal frame. Synchronize playback by these timestamps; hold an ended episode's final frame and display its outcome. Video frame rate follows the actual control-step recording cadence, rather than unrelated renderer metadata.

Generate checksums and a manifest without a self-referential hash cycle. The manifest can hash payload files, while the checksum file covers the manifest and declared payload files but excludes itself. The clean reader validates expected roles, missing files, safe paths, schema versions, archive limits, and hashes before exposing the case as verified. Load numerical archives without pickle.

## Build order and evidence gates

| Gate | Deliverable | Passing evidence |
| --- | --- | --- |
| A. Runtime feasibility | Diagnostic CLI and target-host manifest | Real CUDA operation, both camera frames, exact upstream versions, full policy smoke episode |
| B. Reference runner | Task catalog, exact resets, upstream processors, outcome recorder | Qualification counts, correct orientation/state/action pipeline, explicit horizon, queue reset isolation |
| C. Scene contract | Camera/light adapter and corner checks | Identity behavior, actual policy-input changes, unchanged initial mechanics, clean restoration |
| D. Episode artifacts | Immutable episode publication and reader | Both cameras, typed trace, unambiguous timestamps, required hashes, reopen in separate process |
| E. Bounded investigation | Shared search/reduction/confirmation domain functions | Proposal reproducibility, witness rule, complete ledger, successful and unsuccessful synthetic search tests |
| F. Durable service | FastAPI, SQLite repositories, worker supervision | Idempotent submission, cancellation, lease fencing, partial-candidate recovery, crash-window recovery |
| G. Product interface | Setup, search, campaign, case, export surfaces | Entire genuine-evidence journey, fresh rerun, truthful worker state, accessible playback and measured-point display |
| H. Release | Clean install instructions, genuine example bundle, declared study report | New-machine reader validation, target-host rerun, disclosed no-find/errors, measured costs, working declared access mode |

Work on lightweight contracts and reader interfaces can proceed on the laptop while target-host feasibility is established. Detailed scientific comparisons remain blocked on the real adapter checks, rather than on frontend scaffolding.

High-value fault tests include lost lease during artifact publication, an API request repeated with the same idempotency key, cancellation after reservation, crash after file publication but before database commit, a partially completed two-state candidate, a corrupt bundle, and reduction on a deliberately nonmonotonic synthetic surface. These tests validate application invariants; only the target-host integration suite validates robot behavior.

## Submission considerations, if pursuing the guide's hackathon path

The current official rules and FAQ require meaningful Kiro use, a committed root `.kiro` directory, a public licensed GitHub repository, a functional application URL, and a public demonstration video under three minutes. Creating a directory by itself does not demonstrate actual Kiro development. Keep genuine assistance/validation evidence as work happens.

The verified submission deadline is 5 December 2026 at 06:00 Singapore time. Free judging access extends through 30 January 2027 at 05:00 Singapore time. Do not claim that a recorded explorer automatically satisfies fresh-execution access. Match the submitted capability and testing instructions to the actual deployment, and seek organizer clarification if relying solely on an explorer and downloadable build.

No submission, account action, publishing, or organizer contact was performed in this review.

## Selected primary sources

- [LeRobot v0.6.1 release](https://github.com/huggingface/lerobot/releases/tag/v0.6.1)
- [Pinned LeRobot LIBERO wrapper](https://raw.githubusercontent.com/huggingface/lerobot/v0.6.1/src/lerobot/envs/libero.py)
- [Pinned environment processors](https://raw.githubusercontent.com/huggingface/lerobot/v0.6.1/src/lerobot/processor/env_processor.py)
- [Pinned evaluation pipeline](https://raw.githubusercontent.com/huggingface/lerobot/v0.6.1/src/lerobot/scripts/lerobot_eval.py)
- [Pinned SmolVLA implementation](https://raw.githubusercontent.com/huggingface/lerobot/v0.6.1/src/lerobot/policies/smolvla/modeling_smolvla.py)
- [Selected checkpoint snapshot](https://huggingface.co/lerobot/smolvla_libero/tree/a24f1f380461b665158d52acd140152c79e8b36d)
- [NVIDIA CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [SQLite WAL behavior and fixed versions](https://sqlite.org/wal.html)
- [Official hackathon rules](https://kiroween.devpost.com/rules)
- [Official hackathon FAQ](https://kiroween.devpost.com/details/faqs)

**Remaining unknowns:** access to the separate execution PC; its actual software/driver state; combined simulator/render/model compatibility; baseline task competence; available initial-state inventory; valid scene corners; episode time, memory and storage costs; real failure discovery; reduction repeatability; and the eventual public-access mode. None is established by document or source review alone.
