# Bounded project sweeps

A project sweep evaluates one physical input across two to sixteen declared values. The list must increase strictly and include the reference value from the base inputs. FailureForge freezes the project revision and keeps every other input, asset, controller, acceptance limit and parameter binding fixed. Each point has its own immutable suite run and evidence.

The project sweep catalog lists permissible inputs. The robot adapter accepts `targets.<joint name>` in radians or metres according to the selected joint. The beam supports dimensions, elastic modulus, tip force and distributed load. The rod supports dimensions, conductivity, left and right boundary temperatures, and volumetric heat generation. The selected field requires an explicit numeric value in the base inputs. Other supported inputs can retain their project-parameter bindings. Beam and rod runs need a declared acceptance limit to produce a pass/fail outcome.

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
