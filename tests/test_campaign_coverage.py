from fastapi.testclient import TestClient

from failureforge.api import create_app
from failureforge.campaign_coverage import campaign_coverage, flatten_controls


def test_coverage_counts_requested_levels_and_only_isolated_qualified_verdict_changes():
    meta = {"kind": "suite", "project_id": "p", "suite_id": "s"}
    declared = [
        {"name": "Trays", "field": "payload_kg", "unit": "kg", "required_values": [0, 0.5, 0.7]},
        {"name": "Force", "field": "head_force_n", "unit": "kN", "required_values": [0.002]},
        {"name": "Wrong dimension", "field": "head_force_n", "unit": "K", "required_values": [310]},
        {"name": "Humidity", "field": "humidity_pct", "required_values": [85]},
    ]
    def record(identifier, mass, force, category, runtime="v1", **extra):
        return {"id": identifier, "adapter": "packaging_lift", "category": category,
                "revision": 1, "runtime": runtime, "controls": {"payload_kg": mass, "head_force_n": force, **extra}}
    records = [
        record("light", 0, 0, "passed"), record("no-load", 0.5, 0, "passed"),
        record("full", 0.5, 2, "failed"), record("bad-checks", 0, 2, "blocked"),
        record("pending", 0.7, 0, "pending"), record("different-build", 0.7, 2, "passed", runtime="v2"),
        record("different-rule", 0.5, 3, "passed", max_error=0.2)]
    group, = campaign_coverage(meta, records, declared)["groups"]
    assert group["counts"] == {"planned": 7, "passed": 4, "failed": 1, "pending": 1,
                               "blocked": 1, "measurement_only": 0}
    assert group["grid"] == {"possible_cells": 9, "planned_cells": 7, "observed_cells": 5, "unobserved_cells": 4}
    fields = {f["field"]: f for f in group["factors"]}
    assert fields["head_force_n"]["isolated_pairs"] == fields["head_force_n"]["verdict_changes"] == 1
    assert group["matched_change"] == {"field": "head_force_n", "pass_run_id": "no-load",
                                       "fail_run_id": "full", "pass_value": 0, "fail_value": 2}
    assert [(f["status"], f["untested_values"]) for f in group["declared_factors"]] == [
        ("varied", []), ("varied", []), ("unit_mismatch", None), ("unmapped", [85])]


def test_acceptance_threshold_flip_is_not_a_physical_input_comparison():
    records = [dict(id=str(i), adapter="structural_beam", category=category, revision=4, runtime="v1",
                    controls={"tip_force_n": 5, "max_displacement_m": limit})
               for i, (limit, category) in enumerate([(.001, "passed"), (.0005, "failed")])]
    group, = campaign_coverage({"kind": "suite", "project_id": "p", "suite_id": "s"}, records, [])["groups"]
    assert group["matched_change"] is None
    assert all(field["isolated_pairs"] == 0 for field in group["factors"])


def test_blocked_cells_keep_the_full_two_by_three_denominator():
    records = [dict(id=f"{load}-{heat}", adapter="packaging_lift", revision=1, runtime="v1",
                    controls={"payload_kg": load, "head_force_n": heat},
                    category="blocked" if load and heat else "passed")
               for load in (0, 0.5) for heat in (0, 1, 2)]
    meta = {"kind": "matrix", "project_id": "p", "suite_id": "s"}
    group, = campaign_coverage(meta, records, [])["groups"]
    assert group["grid"] == {"planned_cells": 6, "possible_cells": 6, "observed_cells": 4, "unobserved_cells": 2}
    assert group["counts"]["blocked"] == 2
    assert group["missing_combinations"] == [{"head_force_n": 1, "payload_kg": 0.5},
                                             {"head_force_n": 2, "payload_kg": 0.5}]
    for record in records:
        record["category"] = "passed"
    assert campaign_coverage(meta, records, [])["groups"][0]["grid"]["observed_cells"] == 6


def test_measurement_only_nested_joint_grid_and_unrepresented_cartesian_product():
    count = 16
    records = [dict(id=str(i), adapter="robot_motion", category="measurement_only",
                    revision=1, runtime="v1", controls=flatten_controls({
                        "targets": {f"j.{n}": i for n in range(64)}}),
                    joints=[{"name": "j.0", "type": "revolute", "unit": "rad", "mimic": None}])
               for i in range(count)]
    group, = campaign_coverage({"kind": "suite", "project_id": "p", "suite_id": "s"}, records,
                               [{"name": "Joint", "field": "targets.j.0", "unit": "rad",
                                 "required_values": [2, 0.5]}])["groups"]
    assert group["grid"]["observed_cells"] == count and group["grid"]["possible_cells"] is None
    assert group["matched_change"] is None
    assert group["declared_factors"][0]["untested_values"] == [0.5]
    assert all(f["isolated_pairs"] == 0 for f in group["factors"])


def test_contradictory_repetitions_are_excluded_from_matched_verdict_changes():
    meta = {"kind": "suite", "project_id": "p", "suite_id": "s"}
    records = [dict(id=str(i), category=category, adapter="packaging_lift", revision=1, runtime="v1",
                    controls={"payload_kg": 0.5, "head_force_n": force})
               for i, (force, category) in enumerate(((0, "passed"), (0.0, "failed"), (2, "failed")))]
    group, = campaign_coverage(meta, records, [])["groups"]
    assert group["matched_change"] is None and group["conflicting_repeat_runs"] == ["0", "1"]
    force = next(f for f in group["factors"] if f["field"] == "head_force_n")
    assert force["isolated_pairs"] == 2 and force["verdict_changes"] == 0


def test_mixed_joint_units_and_inspection_adapters_do_not_claim_a_physical_grid():
    meta = {"kind": "suite", "project_id": "p", "suite_id": "s"}
    records = [{"id": unit, "adapter": "robot_motion", "category": category, "revision": 1,
                "runtime": "v1", "controls": {"targets.base": value, "model_asset_id": unit},
                "joints": [{"name": "base", "unit": unit, "type": kind}]}
               for unit, category, value, kind in [("rad", "passed", 0.1, "revolute"), ("m", "failed", 0.2, "prismatic")]]
    records.append({"id": "cad", "adapter": "cad_inventory", "controls": {"units": "mm"},
                    "category": "measurement_only", "revision": 1, "runtime": "v1"})
    cad, robot = campaign_coverage(meta, records, [{"field": "targets.base", "unit": "", "required_values": [0.1]}])["groups"]
    assert cad["grid"]["possible_cells"] is None and cad["factors"] == []
    assert robot["grid"]["possible_cells"] is None and robot["matched_change"] is None
    assert robot["declared_factors"][0]["status"] == "unit_mismatch" and robot["declared_factors"][0]["untested_values"] is None


def test_coverage_uses_frozen_declarations_and_missing_matrix_ordinal(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)  # Hold the queue for deterministic missing/pending evidence.
    spec = {"name": "Lift", "analysis_type": "robot_behavior", "entry_stage": "prototype",
            "robot_source": "supported", "robot_template": "packaging_lift_v1", "goal": "Lift a tray",
            "success_criteria": "Hold position", "operating_factors": [
                {"name": "Payload", "field": "payload_kg", "unit": "kg", "required_values": [0, 0.5, 1]}]}
    owner = client.post("/api/projects", json=spec).json()["id"]
    path = f"/api/projects/{owner}"
    catalog = client.get(f"/api/project-campaigns/{owner}/coverage/catalog").json()
    assert {"payload_kg", "head_force_n", "targets.*"} == {f["field"] for f in catalog["factors"]}
    suite = client.post(f"{path}/environment-matrices", json={
        "expected_revision": 1, "label": "Tray", "adapter": "packaging_lift",
        "payload_kg": [0, 0.5], "head_force_n": [0, 2], "reference": {"payload_kg": 0, "head_force_n": 0}}).json()["suite_id"]
    endpoint = f"/api/project-campaigns/{owner}/{suite}/coverage"
    assert client.post(path, json={**spec, "operating_factors": [], "expected_revision": 1}).status_code == 200
    with app.state.store.connection(True) as db:
        db.execute("DELETE FROM project_runs WHERE suite_id=? AND ordinal=2", (suite,))
    group, = client.get(endpoint).json()["groups"]
    assert group["counts"]["planned"] == 4 and group["counts"]["pending"] == 3 and group["counts"]["blocked"] == 1
    assert group["grid"] == {"planned_cells": 4, "observed_cells": 0, "possible_cells": 4, "unobserved_cells": 4}
    assert group["declared_factors"][0]["untested_values"] == [0, 0.5, 1]
    assert group["declared_factors"][0]["status"] == "unobserved"
    assert client.get(f"/api/project-campaigns/wrong/{suite}/coverage").status_code == 404
