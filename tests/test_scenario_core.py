import copy

import pytest
from pydantic import ValidationError

from failureforge.contracts import config_hash
from failureforge.project_runs import ProjectTest
from failureforge.project_solver import run_job
from failureforge.scenario_core import BatchDraft, CandidateDraft, TIMED_LIFT, build_context, compile_candidate


def project(analysis="structural"):
    return {"id": "project_a", "revision": 7, "name": "Customer prototype", "entry_stage": "prototype",
            "analysis_type": analysis, "goal": "Carry a load at the delivery station.",
            "success_criteria": "Keep deflection within the declared limit.",
            "robot_source": "supported" if analysis == "robot_behavior" else "custom",
            "robot_template": "packaging_lift_v1" if analysis == "robot_behavior" else None,
            "parameters": [], "test_plans": [], "operating_factors": [], "assets": []}


def reference(p, adapter, inputs):
    job = {"adapter": adapter, "analysis_type": p["analysis_type"], "inputs": inputs, "assets": {}}
    evidence = {"snapshot": p, "inputs": inputs, "adapter": adapter, "runtime": {"test": "cpu"},
                "result": run_job(job)}
    return {**evidence, "project_id": p["id"], "project_revision": p["revision"], "id": "run_ref",
            "status": "completed", "evidence_hash": config_hash(evidence)}


def beam(**fields):
    return {"length_m": 0.2, "width_m": 0.02, "height_m": 0.01, "young_modulus_pa": 70e9,
            "distributed_load_n_per_m": 25, "max_displacement_m": 0.0001, **fields}


def draft(**kwargs):
    return CandidateDraft.model_validate({
        "title": "Load reaches the free end", "hypothesis": "An item sliding out increases deflection.",
        "operation_id": "beam.load.tip_resultant", "fact_refs": ["project.goal", "baseline.length_m"],
        "assumptions": ["The item can reach the free end."], "missing_capability": None,
        "question": "Can the load act at the free end?", "shift_ms": None, **kwargs,
    })


def test_equal_resultant_executes_on_frozen_model_and_groups_equivalent_pressure():
    p = project()
    instance_hashes = []
    for inputs in (beam(), beam(distributed_load_n_per_m=0, face_pressure_pa=1250)):
        packet = build_context(p, reference(p, "structural_beam", inputs))
        ids = {op["id"] for op in packet["operations"]}
        assert "beam.load.tip_resultant" in ids and "beam.load.uniform_resultant" not in ids
        d = draft()
        preview = compile_candidate(packet, d)
        assert preview["state"] == "needs_information" and preview["variant"]["inputs"]["tip_force_n"] == 5
        result = compile_candidate(packet, d, confirmed=True)
        assert result["state"] == "ready" and result["fingerprint"] != preview["fingerprint"]
        assert result["observables"] == ["Maximum absolute deflection ≤ 0.0001 m"]
        tests = [ProjectTest.model_validate(result[key]) for key in ("reference", "variant")]
        runs = [run_job({"adapter": test.adapter, "analysis_type": "structural", "inputs": test.inputs, "assets": {}})
                for test in tests]
        assert [r["passed"] for r in runs] == [True, False]
        assert [r["summary"]["continuous_max_abs_displacement_m"] * 1000 for r in runs] == pytest.approx(
            [0.042857142857, 0.114285714286])
        assert not set(result["diff"]) - {"tip_force_n", "distributed_load_n_per_m", "face_pressure_pa"}
        renamed = compile_candidate(packet, d.model_copy(update={"title": "Alternate description"}), True)
        assert result["family_key"] == renamed["family_key"]
        assert result["instance_hash"] == renamed["instance_hash"]
        assert result["fingerprint"] != renamed["fingerprint"]
        instance_hashes.append(result["instance_hash"])
        same_distribution = compile_candidate(packet, draft(operation_id="beam.load.uniform_resultant"), True)
        assert same_distribution["state"] == "invalid" and not same_distribution["variant"]
    assert len(set(instance_hashes)) == 1


def test_reviewed_layouts_each_apply_the_declared_resultant_to_the_uploaded_design():
    p = project()
    inputs = beam(distributed_load_n_per_m=35)
    c = build_context(p, reference(p, "structural_beam", inputs))
    magnitude = 35 * inputs["length_m"]
    observed = {}
    for op in c["operations"]:
        compiled = compile_candidate(c, draft(operation_id=op["id"]), True)
        assert compiled["state"] == "ready" and compiled["instance_hash"] not in observed
        job = compiled["variant"]
        result = run_job(dict(adapter=job["adapter"], inputs=job["inputs"], analysis_type="structural", assets={}))
        assert result["inputs"]["young_modulus_pa"] == inputs["young_modulus_pa"]
        assert result["acceptance_checks"][0]["maximum"] == inputs["max_displacement_m"]
        if op["id"] == "beam.load.remove_applied":
            assert result["summary"]["root_reaction_n"] == 0 and compiled["family_key"] == "beam.payload_removal"
        else:
            assert result["summary"]["root_reaction_n"] == pytest.approx(-magnitude)
            assert compiled["family_key"] == "beam.load_placement"
        observed[compiled["instance_hash"]] = result["summary"]["continuous_max_abs_displacement_m"]
    assert len(observed) == len(set(observed.values())) == 6


def test_same_reference_layout_is_identified_across_split_patches_and_cited_in_context():
    p = project()
    patches = [{"start_fraction": a, "end_fraction": b, "force_n": 2.5} for a,b in [(0., .25), (.25, .5)]]
    c = build_context(p, reference(p, "structural_beam", beam(distributed_load_n_per_m=0, span_loads=patches)))
    assert "beam.load.inner_half_patch" not in {op["id"] for op in c["operations"]}
    assert {item["id"] for item in c["facts"]} >= {"baseline.span_loads.1.force_n", "baseline.span_loads.2.end_fraction"}


def test_current_pulse_and_early_pulse_include_both_phase_outcomes():
    p = project("robot_behavior")
    packet = build_context(p, reference(p, "packaging_lift", {"payload_kg": 0.5, "head_force_n": 2}))
    assert [op["id"] for op in packet["operations"]] == ["lift.head.shift_onset"]
    assert packet["operations"][0]["shift_bounds_ms"] == [-1000, -1]
    assert "onset 1000 ms, duration 1000 ms" in packet["operations"][0]["description"]
    d = draft(operation_id="lift.head.shift_onset", fact_refs=["project.goal", "baseline.head_force_n"],
              shift_ms=-250, title="Head begins pressing during ascent")
    preview = compile_candidate(packet, d)
    assert "timed fixture" in preview["reason"]
    result = compile_candidate(packet, d, True)
    assert result["state"] == "ready" and result["diff"] == {"head_onset_ms": {"reference": 1000, "variant": 750}}
    tests = [ProjectTest.model_validate(result[key]) for key in ("reference", "variant")]
    assert [t.adapter for t in tests] == [TIMED_LIFT, TIMED_LIFT]
    measured = [run_job({"adapter": t.adapter, "inputs": t.inputs, "analysis_type": "robot_behavior", "assets": {}})
                for t in tests]
    assert [r["criteria"]["arrived_within_tolerance"] for r in measured] == [True, False]
    assert [r["criteria"]["held_within_tolerance"] for r in measured] == [False, False]
    assert compile_candidate(packet, d.model_copy(update={"shift_ms": 50}), True)["state"] == "invalid"


@pytest.mark.parametrize(("onset", "duration", "force", "bounds"), [
    (0, 1999, 2, [1, 1]),
    (750, 1000, 2, [-750, 250]),
    (1, 1999, 2, [-1, -1]),
    (0, 2000, 2, None),
    (750, 1000, 0, None),
])
def test_timed_operation_only_advertises_shifts_that_fit_the_actual_reference(onset, duration, force, bounds):
    p = project("robot_behavior")
    inputs = {"payload_kg": 0.5, "head_force_n": force, "head_onset_ms": onset, "head_duration_ms": duration}
    packet = build_context(p, reference(p, TIMED_LIFT, inputs))
    candidate = draft(operation_id="lift.head.shift_onset", fact_refs=["baseline.head_onset_ms"], shift_ms=1)
    if bounds is None:
        assert packet["operations"] == []
        assert compile_candidate(packet, candidate, True)["variant"] is None
        return
    entry, = packet["operations"]
    assert entry["shift_bounds_ms"] == bounds and f"onset {onset} ms, duration {duration} ms" in entry["description"]
    for shift in set(bounds):
        result = compile_candidate(packet, candidate.model_copy(update={"shift_ms": shift}), True)
        assert result["state"] == "ready"
    for shift in (0, bounds[0] - 1, bounds[1] + 1):
        assert compile_candidate(packet, candidate.model_copy(update={"shift_ms": shift}), True)["variant"] is None


def test_baseline_evidence_and_compilation_are_project_scoped():
    p = project()
    run = reference(p, "structural_beam", beam())
    with pytest.raises(ValueError, match="current revision"):
        build_context({**p, "revision": 8}, run)
    with pytest.raises(ValueError, match="belonging to this project"):
        build_context({**p, "id": "another"}, run)
    with pytest.raises(ValueError, match="checksum"):
        build_context(p, {**run, "inputs": beam(tip_force_n=20)})
    packet = build_context(p, run)
    changed_packet = copy.deepcopy(packet)
    changed_packet["baseline"]["inputs"]["max_displacement_m"] = 1
    assert compile_candidate(changed_packet, draft(), True)["state"] == "invalid"
    assert compile_candidate(packet, draft(fact_refs=["asset.some_other_project"]), True)["state"] == "invalid"
    assert compile_candidate(packet, draft(operation_id="invented.operation"), True)["state"] == "invalid"
    blocked = compile_candidate(packet, draft(missing_capability="Requires measured impact/contact dynamics."), True)
    assert blocked["state"] == "needs_capability" and blocked["variant"] is None


def test_beam_without_limit_compiles_an_observation_without_inventing_a_rule():
    p = project()
    packet = build_context(p, reference(p, "structural_beam", beam(max_displacement_m=None)))
    compiled = compile_candidate(packet, draft(), confirmed=True)
    assert compiled["state"] == "ready"
    assert compiled["observables"] == ["Compare maximum absolute deflection (mm) across both runs. No acceptance limit supplied."]
    for role in ("reference", "variant"):
        assert "max_displacement_m" not in compiled[role]["inputs"]
        assert "max_surface_stress_pa" not in compiled[role]["inputs"]


def test_planning_with_opaque_upload_cannot_execute_or_claim_material():
    p = project()
    p["assets"] = [{"id": "asset_1", "kind": "cad", "filename": "case.step", "sha256": "a" * 64,
                    "inspection": {"status": "stored", "summary": "Original file retained."}}]
    packet = build_context(p, task="Move the part between stations.")
    assert packet["operations"] == [] and packet["baseline"] is None
    assert {f["id"] for f in packet["facts"]} == {"project.goal", "project.success_criteria", "asset.asset_1", "task"}
    planning = draft(operation_id=None, fact_refs=["task", "asset.asset_1"], question="What supports the part?")
    assert compile_candidate(packet, planning, True)["state"] == "needs_information"
    with pytest.raises(ValidationError):
        CandidateDraft.model_validate({**planning.model_dump(), "max_displacement_m": 999})
    with pytest.raises(ValidationError):
        CandidateDraft.model_validate({**planning.model_dump(), "shift_ms": "250"})
    assert BatchDraft(candidates=[], clarifications=["What is the target drop tolerance?"]).clarifications
    with pytest.raises(ValidationError):
        BatchDraft(candidates=[], clarifications=[])
