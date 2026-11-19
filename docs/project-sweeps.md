# Bounded project sweeps

A project sweep evaluates one physical input across two to sixteen declared values. The list must increase strictly and include the reference value from the base inputs. FailureForge freezes the project revision and keeps every other input, asset, controller, acceptance limit and parameter binding fixed. Each point has its own immutable suite run and evidence.

The project sweep catalog lists permissible inputs. The robot adapter accepts `targets.<joint name>` in radians or metres according to the selected joint. The beam supports dimensions, elastic modulus, tip force, distributed load and signed face pressure. The rod supports dimensions, conductivity, volumetric heat generation and boundary temperatures, including the ambient temperature and film coefficient for a convective right end. Each selected field requires an explicit numeric value in the base inputs. Other inputs can retain their parameter bindings. Beam and rod runs need a declared acceptance limit to produce a pass/fail outcome. Use **Cross two inputs** to test the joint effect of two supported controls on one prototype revision.

Use `GET /api/projects/{project}/sweeps/catalog` to inspect available fields and units. Send this example body to `POST /api/projects/{project}/sweeps` on a matching structural project. A repeated submission with the same `Idempotency-Key` and request returns the same suite.

```json
{
  "expected_revision": 1,
  "label": "Signed tip load",
  "adapter": "structural_beam",
  "field": "tip_force_n",
  "values": [-10, -5, 0, 5, 10],
  "inputs": {
    "length_m": 0.2, "width_m": 0.02, "height_m": 0.01,
    "young_modulus_pa": 70000000000, "tip_force_n": 0,
    "max_displacement_m": 0.00015
  }
}
```

Read `GET /api/projects/{project}/sweeps/{suite_id}` for each point and its underlying run ID. The reference and nearest observed failing coordinate are reported explicitly. Equal distances select the lower coordinate. A failing reference has distance zero. The report makes no estimate for gaps and performs no interpolation.

The counts distinguish passing, failing, pending, blocked and measurement-only points. The measured count covers completed computations, including any later blocked by diagnostics, model applicability or robot qualification. A successful computation without a declared acceptance rule remains measurement-only. A failed or interrupted execution retains its status and reason. The underlying run contains complete solver diagnostics, traces and provenance. A sweep can finish without observing any failing point.

The [OpenManipulator-X study](../examples/openmanipulator-x/README.md) includes a worked five-point joint-speed sweep, independent of its physical-log calibration.

## Worked two-factor cooling study

The saved thermal project tested one 0.10 m rod of cross-sectional area 0.0004 m² and conductivity 15 W/(m·K). All four conditions used a 300 K left end, 60,000 W/m³ internal heat generation, 16 coarse elements and a maximum allowed temperature of 315 K. The right face exchanged heat with an external fluid. The two ambient temperatures and two film coefficients below were chosen to exercise the model. They are illustrative operating settings.

| Ambient temperature | End-face film coefficient | Simulated continuous peak | Verdict |
| --- | --- | --- | --- |
| 290 K | 100 W/(m²·K) | 309.800 K | Pass |
| 290 K | 10 W/(m²·K) | 318.169 K | Fail |
| 310 K | 100 W/(m²·K) | 316.200 K | Fail |
| 310 K | 10 W/(m²·K) | 319.380 K | Fail |

All four combinations completed with numerical evidence. Each camera inspection visualizes the saved steady-state temperature field. Use the continuous peak for the acceptance decision. The colors correspond to the nodal values and scale printed on each inspection. [Open the saved campaign on the execution PC](http://127.0.0.1:8000/#/projects/project_45e95407f1424ff39ac72c7d83a35ab0/analysis?batch=suite_1fe0ba5e995e418bb90dddbbc382c161)
