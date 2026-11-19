# FailureForge

A local workspace for preparing hardware tests and investigating failures of a supported robot policy in simulation.

Projects now accept five starting points: concept, CAD design, robot model, existing simulation, and physical prototype. Save requirements, attach files, record physical properties and their sources, define multiple test plans, and review the preparation checklist. Robot behavior, structural, and thermal projects have separate input guidance. These are preparation workflows; custom robot execution, calibration, general regression suites, and structural/thermal solvers are planned integrations.

The application implements durable campaigns, three search strategies, matched reference comparisons, bounded reduction, confirmation, fresh paired reruns, trace inspection, and verified case exports. The real LIBERO/SmolVLA integration is implemented against the pinned upstream sources but **has not yet been executed or qualified on the RTX 5090 PC**. Robot results are unavailable until that qualification passes.

## Run on the laptop

Requires Python 3.11 or 3.12 and Node 22 or later. These commands install the lightweight application; they do not download models or install CUDA.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r environment-app-lock.txt
.venv/Scripts/python.exe -m pip install -e . --no-deps
cd apps/web
npm ci
npm run build
cd ../..
.venv/Scripts/python.exe -m failureforge dev --synthetic
```

Open **http://127.0.0.1:8000** for the landing page, then choose **Start a project** (project list: `http://127.0.0.1:8000/#/projects`). The existing benchmark remains under **Campaigns**. The landing page includes an illustrative interactive 3D scene; its artwork is not recorded robot evidence. The explicit `--synthetic` flag starts a separate diagnostic worker. Choose **Synthetic validation** in the campaign form to exercise the application. All such results and bundles carry a synthetic label. They contain a mathematical diagnostic trace and no fabricated robot videos.

To inspect existing evidence without running any worker:

```powershell
.venv/Scripts/python.exe -m failureforge serve
```

For frontend hot reload, run `npm run dev` in `apps/web` while the API runs on port 8000. Vite proxies `/api` to the local service. The production build is served directly by FastAPI. Both bind to loopback by default.

## Project preparation

The three-step setup asks for your starting stage, analysis, and working brief. Each project provides **Overview**, **Files**, **Parameters**, and **Test plans** sections. Saved changes use revision checks to prevent silent overwrites; uploads also update the revision. Export the saved preparation report as JSON for review or handoff.

The service accepts up to 40 files per project, 10 MiB per file, 80 parameters, and 30 test plans. Supported XML and JSON files have a stricter 2 MiB limit and bounded syntax inspection. URDF/MJCF inventories can flag missing explicit inertia and unresolved references. These checks do not compile a model or establish physical validity. CAD, controller packages, images, and other attachments remain opaque; archives are not extracted and uploaded code is not executed. All new project execution gates remain closed pending an appropriate validated adapter.

See the [detailed journey and architecture guide](docs/product-journeys-and-architecture.md), also available as a [17-page PDF](output/pdf/failureforge-product-journeys.pdf), for nine customer journeys, required inputs, outputs, technical choices, and staged acceptance criteria.

## RTX 5090 execution host

Follow [the robotics setup guide](docs/robotics-setup.md). Keep the checkout, SQLite database, and artifact store on the Linux filesystem. The API and worker use separate Python environments on the same host. The worker environment preserves the frozen LeRobot lock; it does not install the web application's dependency pins over the robotics stack.

Qualification runs ten nominal task episodes, two search-state reference episodes, and controlled scene probes. Inspect the generated main/wrist camera contact sheet and record approval only after checking orientation, target visibility, and changes. The worker verifies runtime identity and evidence hashes before live execution. GPU integration tests are opt-in.

The live backend supports only:

- LeRobot v0.6.1 with the frozen dependency profile.
- `lerobot/smolvla_libero` revision `a24f1f380461b665158d52acd140152c79e8b36d`.
- LIBERO-Spatial task `pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate` (asserted by name).
- Main-camera parent-frame x displacement between -0.04 and +0.04 metres, and lighting scale between 0.70 and 1.30.
- One policy and one environment, sequential episodes, 20 Hz control and a 280-step horizon.

## Workflow

1. Create a bounded campaign. Each candidate uses the same two search states; two nominal screening episodes are budgeted separately at campaign start.
2. Inspect measured candidate points and the selected failure pair. Unknown regions have no assigned outcome.
3. Request reduction. It freezes the original failing state IDs, verifies reference/changed pairs, tries a finite nonmonotonic reduction design, and verifies the retained witness again.
4. Confirm the selected case on ten untouched states. Confirmation freezes the selection; subsequent reduction is rejected.
5. Request a fresh rerun. This explicitly allocates two additional episodes: reference and changed conditions on the first frozen failing state. Existing outcomes remain visible.
6. Export a bundle and validate it in a clean reader process. Every included execution has its own state, timestamps, trace, provenance and outcome. Real robot episodes include both camera recordings.

The default campaign allowance is 64 search + 32 reduction + 20 confirmation episodes, plus two separately shown baseline-screening episodes and at most two infrastructure retries: **120 total attempted episodes**. This is the brief's 118-attempt campaign plus the explicit two-episode screening allocation. Ten task-qualification episodes, additional studies and user-requested reruns have separate allocations. A campaign with no observed failures completes successfully and says so.

The 8-, 16- and 32-candidate presets keep complete two-state evaluations. Adaptive search begins with up to 16 Sobol warm-up candidates; only the 32-candidate preset reaches local refinement. Proposal reasons and incomplete/error attempts remain recorded. Synthetic findings establish application behavior only.

## Command line

Commands share the same persistence, engine, and artifact code as the API. Put `--data-dir PATH` before the subcommand. Default data lives in ignored `data/`.

```powershell
.venv/Scripts/python.exe -m failureforge doctor
.venv/Scripts/python.exe -m failureforge catalog
.venv/Scripts/python.exe -m failureforge search --spec configs/synthetic-campaign.json
.venv/Scripts/python.exe -m failureforge worker --backend synthetic --once
.venv/Scripts/python.exe -m failureforge report CAMPAIGN_ID
.venv/Scripts/python.exe -m failureforge reduce CASE_ID
.venv/Scripts/python.exe -m failureforge confirm CASE_ID
.venv/Scripts/python.exe -m failureforge rerun CASE_ID
.venv/Scripts/python.exe -m failureforge export CASE_ID
.venv/Scripts/python.exe -m failureforge inspect-bundle PATH.zip
.venv/Scripts/python.exe -m failureforge rerun-bundle PATH.zip --backend synthetic
```

Search and case operations enqueue jobs. Use a continuously running worker or another `worker --once` invocation to execute them. `rerun-bundle` verifies its archive and executes a fresh paired rerun in an idle local queue. It does not execute imported scripts or deserialize pickle objects.

## Reliability and limits

SQLite transactions reserve episode allowances before work starts. Unique lease tokens fence completion; a stale worker cannot expose its artifacts. Attempts have immutable directories, and artifact visibility follows the database commit. A directory left by an interrupted worker is unreferenced rather than presented as complete evidence. Started or uncertain attempts stay charged.

Expired jobs become interrupted. `failureforge resume JOB_ID` explicitly resumes them, reusing only hash-validated completed episodes and retaining saved candidate proposals. Cancellation is cooperative; the real runner operates in a persistent subprocess with a configurable wall-time watchdog. A stuck process is terminated and recreated. The default per-episode timeout is 300 seconds, including initial load; adjust it deliberately for the execution host.

On SQLite runtimes with the documented WAL fix, the store uses WAL. Older runtimes explicitly use the rollback journal and report this in `doctor`; the laptop's Python may bundle an older SQLite. The database is never intended for a network share. The repository's `Store.backup()` uses SQLite's backup API.

Private deployment requires an API token, explicit allowed origins, and TLS through a reverse proxy. `FAILUREFORGE_API_TOKEN` enables bearer authentication; `FAILUREFORGE_ORIGINS` is a comma-separated allowlist. The CLI rejects a non-loopback bind without a token. The first release is intended for local access; no public service is deployed by this repository.

For the laptop browser to use the PC, keep the PC service on `127.0.0.1:8000` and forward it over your existing SSH connection: `ssh -N -L 8000:127.0.0.1:8000 USER@PC`. Then open `http://127.0.0.1:8000` on the laptop. Stop the laptop's own preview first so port 8000 is free. SSH authenticates and encrypts this connection. The bundled browser UI assumes this same-origin local/tunneled access; direct bearer-authenticated API deployment requires a separately configured gateway.

## Verification

```powershell
.venv/Scripts/python.exe -m pytest --basetemp=tmp/pytest-local
cd apps/web
npm test
npm run build
```

The workspace `--basetemp` avoids restricted Windows system-temp directory rename behavior. Tests cover finite bounds, state-bank separation, deterministic search, nonmonotonic reduction, phase budgets, shared retries, API idempotency, cancellation, stale leases, partial-candidate resume, the process watchdog, corruption, nested export validation, and the complete synthetic journey. Project tests cover the stage/analysis matrix, persistence, revision conflicts, upload limits and integrity, hostile structured inputs, and execution gates. Frontend checks cover failure counts, action allowances, and evidence pairing. Synthetic tests do not qualify robot behavior.

Use [the implementation review](docs/implementation-review.md) for the scientific decisions and [build status](docs/build-status.md) for what is implemented versus still awaiting GPU validation. The `.kiro` specifications are prepared project inputs; this repository does not claim that Kiro has already executed them.

## Repository

```text
apps/web/                  React/TypeScript interface
src/failureforge/
  contracts.py             Versioned bounded experiment inputs
  persistence.py           SQLite queue, events, leases and allowances
  artifacts.py             Episode publication and portable bundle reader
  api.py                   Lightweight FastAPI service
  projects.py              Staged project intake, asset storage and readiness
  cli.py                   Shared command line
  search/                  Random, Sobol, adaptive proposals and reduction
  worker/                  Experiment orchestration and process watchdog
  simulation/              Real adapter, qualification and explicit synthetic runner
scripts/                   Robotics bootstrap and schema export
configs/                   Declared experiment examples
tests/                     CPU checks and opt-in GPU integration
```

Third-party software, policies and assets retain their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
