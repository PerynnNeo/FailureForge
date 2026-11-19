# FailureForge

A local workspace for testing a prototype across operating conditions and replaying the evidence for each result.

Open a project and choose **View replays** to play its recorded motion, inspect static fields or explore measured samples. Use **Campaigns → New campaign** to test a group of conditions on any saved project and compare their outcomes. **New bowl benchmark** opens the separate camera-recorded policy experiment. [Audit of the five saved projects](docs/project-workbench-audit.md)

The [packaging lift example](examples/packaging-lift/README.md) tests one fixed prototype across nine external operating conditions. Choose a tray payload and packing-head force in the workbench to see whether the lift reaches its target and holds position through the pressing cycle.

Declare site factors and required operating levels in **Parameters**. Project campaigns can cross two supported inputs, report untested levels and open a matched passing and failing replay. Individual runs with numeric acceptance limits can be checked against an attributed physical trial with recorded settings and measurement uncertainty. [Operating conditions and hardware trials](docs/prototype-environment-test-plan.md)

Projects accept concepts, CAD designs, robot models, existing simulations, and physical prototypes. **Analysis & runs** executes bounded studies, stores immutable evidence, groups studies into suites and compares project revisions. The built-in hand and compatible primitive URDF models support articulated motion. Structural projects support rectangular cantilever bending, and thermal projects support steady one-dimensional conduction. Separate calibration workflows estimate a material property or fit a joint response against held-out physical measurements.

The fixed LIBERO/SmolVLA benchmark runs separately. It supports three search strategies, matched reference comparisons, bounded reduction, held-out confirmation, fresh paired reruns, recorded cameras and verified case exports. Its live worker checks the target host's qualification record before starting a campaign. [Watch the 42-second demo](output/demo/failureforge-demo.mp4) · [See measured results from the RTX 5090](docs/execution-host-results.md) · [Set up an execution host](docs/robotics-setup.md).

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

The service accepts up to 40 files per project, 10 MiB per file, 80 parameters, and 30 test plans. Supported XML and JSON have a 2 MiB intake limit. For execution, each adapter validates its own input contract in a separate solver process. STL inventory supports declared units and optional CSV bill-of-materials mapping. The URDF adapter supports documented joints, physical properties and primitive shapes. The controller format is declarative JSON. Uploaded programs and archives are stored as attachments.

Choose **View replays** inside a project to watch its completed runs from two synchronized cameras. **Campaigns** lets you select a tested condition and watch that run. For local 3D playback, install `python -m pip install -e ".[project-robot]"` in the application environment and install FFmpeg with H.264 encoding and an OpenGL 3.3 renderer. The Linux workbench uses headless EGL. [Project analysis and camera playback](docs/project-analysis.md) · [Articulated motion and upload examples](docs/articulated-motion.md)

The [OpenManipulator-X example](examples/openmanipulator-x/README.md) includes a manufacturer's URDF and two independently recorded physical trials with licenses, source revisions, replayable inputs and held-out calibration measurements. [Project sweeps](docs/project-sweeps.md) explains how to search a finite range and inspect individual outcomes.

The [original roadmap](docs/product-journeys-and-architecture.md) and its [17-page planning PDF](output/pdf/failureforge-product-journeys.pdf) describe the nine customer journeys and their design rationale. Current adapter coverage and limits are in the guides above.

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

### Compare search methods across seeds

Save a JSON study manifest listing the seeds in advance and one campaign ID per seed for each method. Replace the example identifiers with IDs from your local campaigns. Use `null` for an unassigned run so it remains visible in the denominator.

```json
{
  "backend": "synthetic",
  "seeds": [1729, 1730],
  "campaigns": {
    "random": ["campaign_RANDOM_1729", null],
    "sobol": ["campaign_SOBOL_1729", null],
    "sobol_local_mix": ["campaign_MIX_1729", null]
  }
}
```

```powershell
python -m failureforge --data-dir data study-report --manifest study.json
python -m failureforge --data-dir data study-report --manifest study.json --format markdown
```

The report reads a single SQLite snapshot. Compare campaigns with the same backend, domain, candidate budget and state banks. For LIBERO studies, completed episodes must also share a recorded environment fingerprint. The summary lists seeds for which every method completed. A no-find requires a successful search across the full candidate bank. Interrupted or queued jobs retain their own status, and subsequent case work has no effect on a completed search's status.

The first failing candidate is numbered from one and requires both paired search episodes. Search attempts to that observation include charged retries. Baseline screening is counted separately. The JSON includes per-outcome error counts and summed duration of completed search episodes in seconds. The report uses the campaign records and consumes no episode budget.

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

Use [the original implementation review](docs/implementation-review.md) for the scientific decisions and [build status](docs/build-status.md) for measured target-host results. The `.kiro` specifications are prepared project inputs.

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
