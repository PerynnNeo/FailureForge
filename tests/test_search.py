import pytest

from failureforge.search import ReductionPlanner, SearchPlanner, preserves_witness, scene_rank, select_witness
from failureforge.search.planner import DEFAULT_DOMAIN, REFERENCE, scene_key


def history_for(method, seed=1729, n=32):
    planner = SearchPlanner(method, seed)
    history = []
    for index in range(n):
        scene, reason = planner.propose(index, history)
        history.append({"id": str(index), "index": index, "scene_change": scene, "reason": reason,
                        "status": "completed", "score": (index % 3) / 2})
    return history


@pytest.mark.parametrize("method", ["random", "sobol", "sobol_local_mix"])
def test_restarted_planner_preserves_proposals_and_prefix(method):
    history = history_for(method)
    prefix = history[:19]
    restarted = SearchPlanner(method, 1729)
    scene, reason = restarted.propose(19, prefix)
    assert (scene, reason) == (history[19]["scene_change"], history[19]["reason"])
    assert restarted.propose(7, history) == (history[7]["scene_change"], history[7]["reason"])
    assert len({scene_key(row["scene_change"]) for row in history}) == 32
    for row in history:
        assert -0.04 <= row["scene_change"]["main_camera_dx_m"] <= 0.04
        assert 0.7 <= row["scene_change"]["light_scale"] <= 1.3


def test_adaptive_warmup_and_independent_local_streams():
    adaptive = history_for("sobol_local_mix")
    sobol = history_for("sobol")
    assert [row["scene_change"] for row in adaptive[:16]] == [row["scene_change"] for row in sobol[:16]]
    assert any(row["reason"].startswith("local_gaussian") for row in adaptive[16:])
    assert any("sobol_global" in row["reason"] for row in adaptive[16:])
    assert history_for("random", seed=12) != history_for("random", seed=13)


def test_incomplete_candidate_cannot_be_used_to_generate_later_proposals():
    planner = SearchPlanner("sobol", 8)
    first = history_for("sobol", seed=8, n=1)
    first[0]["status"] = "proposed"
    with pytest.raises(ValueError, match="earlier proposal"):
        planner.propose(1, first)
    with pytest.raises(ValueError, match="earlier proposal"):
        planner.propose(2, [])


def test_witness_selection_retains_single_state_failures_and_declared_ties():
    candidates = [
        {"id": "one", "index": 0, "status": "completed", "score": 0.5,
         "scene_change": {"main_camera_dx_m": 0.001, "light_scale": 1.01}},
        {"id": "both", "index": 1, "status": "completed", "score": 1,
         "scene_change": {"main_camera_dx_m": 0.04, "light_scale": 1.3}},
        {"id": "simpler", "index": 2, "status": "completed", "score": 1,
         "scene_change": {"main_camera_dx_m": 0.04, "light_scale": 1.0}},
    ]
    assert select_witness(candidates[:1], DEFAULT_DOMAIN)["id"] == "one"
    assert select_witness(candidates, DEFAULT_DOMAIN)["id"] == "simpler"
    candidates[-1]["status"] = "proposed"
    assert select_witness(candidates, DEFAULT_DOMAIN)["id"] == "both"
    assert select_witness([], DEFAULT_DOMAIN) is None


def test_directional_normalization_and_reference_domain():
    domain = {"main_camera_dx_m": [-0.01, 0.04], "light_scale": [0.8, 1.3]}
    assert scene_rank({"main_camera_dx_m": -0.005, "light_scale": 1}, domain) == (1, 0.5)
    assert scene_rank({"main_camera_dx_m": 0.02, "light_scale": 1}, domain) == (1, 0.5)
    assert scene_rank(REFERENCE, domain) == (0, 0)
    with pytest.raises(ValueError, match="contain the reference"):
        SearchPlanner("sobol", 1, {"main_camera_dx_m": [0.01, 0.04], "light_scale": [0.8, 1.3]})
    with pytest.raises(ValueError, match="proposal resolution"):
        SearchPlanner("sobol", 1, {"main_camera_dx_m": [-1e-12, 1e-12], "light_scale": [0.8, 1.3]})


def test_reduction_measures_grid_without_monotonic_assumption():
    original = {"main_camera_dx_m": 0.04, "light_scale": 1.3}
    planner = ReductionPlanner(original, DEFAULT_DOMAIN)
    proposals = planner.proposals()
    assert 1 <= len(proposals) <= 12
    assert len({scene_key(p["scene_change"]) for p in proposals}) == len(proposals)
    # A success at the smaller quarter point does not suppress a failure island
    # at the half point or exploration of the larger three-quarter point.
    by_dx = {round(p["scene_change"]["main_camera_dx_m"], 3) for p in proposals}
    assert {0.01, 0.02, 0.03} <= by_dx
    incumbent = original
    for proposal in proposals:
        scene = proposal["scene_change"]
        is_failure_island = abs(scene["main_camera_dx_m"] - 0.02) < 1e-8 and abs(scene["light_scale"] - 1.15) < 1e-8
        if is_failure_island and planner.is_improvement(scene, incumbent):
            incumbent = scene
    assert incumbent == {"main_camera_dx_m": 0.02, "light_scale": 1.15}


def test_reduction_freezes_failing_state_set_and_excludes_errors():
    assert preserves_witness({0: "horizon_exhausted", 1: "success"}, [0])
    assert not preserves_witness({0: "success", 1: "horizon_exhausted"}, [0])
    assert not preserves_witness({0: "model_error", 1: "horizon_exhausted"}, [0, 1])
    assert not preserves_witness({0: "horizon_exhausted"}, [0, 1])
    assert preserves_witness({"0": "horizon_exhausted", "1": "terminated_without_success"}, [0, 1])
    assert not preserves_witness({}, [])


def test_reduction_can_contract_after_removing_a_parameter():
    original = {"main_camera_dx_m": 0.04, "light_scale": 1.3}
    planner = ReductionPlanner(original, DEFAULT_DOMAIN)
    incumbent = original
    for proposal in planner.proposals():
        scene = proposal["scene_change"]
        if scene["main_camera_dx_m"] >= 0.02 and planner.is_improvement(scene, incumbent):
            incumbent = scene
    assert incumbent == {"main_camera_dx_m": 0.02, "light_scale": 1.0}
