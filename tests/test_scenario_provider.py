import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from failureforge.contracts import config_hash
from failureforge.project_solver import run_job
from failureforge.scenario_core import build_context, compile_candidate
from failureforge.scenario_provider import TARGET_CASES, LocalProvider, ProviderError, _case_slots


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("FAILUREFORGE_SCENARIO_MODEL", "test-model")
    monkeypatch.delenv("FAILUREFORGE_OLLAMA_PORT", raising=False)
    return LocalProvider()


@pytest.fixture(scope="module")
def beam_packet():
    project = {"id": "test-project", "revision": 1, "analysis_type": "structural", "entry_stage": "cad",
               "goal": "Support the item", "success_criteria": "Limit shelf deflection"}
    path = Path(__file__).resolve().parents[1] / "apps/web/public/examples/beam-reference.json"
    model = json.loads(path.read_text(encoding="utf-8"))
    result = run_job({**model, "assets": {}, "analysis_type": "structural"})
    evidence = {"inputs": model["inputs"], "adapter": model["adapter"], "snapshot": project,
                "runtime": {"test": "cpu"}, "result": result}
    baseline = {**evidence, "project_id": project["id"], "project_revision": 1, "status": "completed",
                "id": "run_ref", "evidence_hash": config_hash(evidence)}
    return build_context(project, baseline, task="Operators move a part along this narrow shelf.")


@pytest.fixture(scope="module")
def packet(beam_packet):
    """A reference runtime that supports only one concrete change uses the single-case path."""
    context = {k: v for k, v in beam_packet.items() if k != "context_hash"}
    context["operations"] = [op for op in context["operations"] if op["id"] == "beam.load.tip_resultant"]
    context["context_hash"] = config_hash(context)
    return context


def local_ollama(monkeypatch, provider, replies=(), *, inventory=None, model_info=None):
    """Record the request the application would send. No sockets or files leave the process."""
    calls = []
    responses = iter(replies)

    def request(path, body=None, timeout=3):
        calls.append((path, copy.deepcopy(body)))
        if path == "/api/tags":
            return {"models": [{"name": "test-model:latest", "digest": "model-sha"}] if inventory is None else inventory}
        if path == "/api/show":
            return model_info or {}
        assert path == "/api/chat"
        return next(responses)

    monkeypatch.setattr(provider, "_request", request)
    return calls


def reply(content, **changes):
    return {"model": "test-model:latest", "done": True, "message": {"content": content},
            "prompt_eval_count": 200, "eval_count": 40, **changes}


def test_cpu_generation_projects_real_registry_and_retries_malformed_data_once(monkeypatch, provider, packet):
    valid = json.dumps({"candidates": [], "clarifications": ["Can the item reach the free end?"]})
    calls = local_ollama(monkeypatch, provider, [reply("{"), reply(valid)])
    assert provider.port == 11434 and provider.status()["available"]
    assert provider.status()["digest"] == "model-sha"
    assert [path for path, _ in calls] == ["/api/tags", "/api/show"]  # Cached local inventory.
    batch, usage = provider.generate(packet, "model-sha")
    assert batch.clarifications == ["Can the item reach the free end?"]
    assert usage == {"attempts": 2, "prompt_tokens": 400, "output_tokens": 80}
    chat, retry = [body for path, body in calls if path == "/api/chat"]
    assert chat["stream"] is False and chat["options"]["num_gpu"] == 0
    props = chat["format"]["$defs"]["CandidateDraft"]["properties"]
    assert props["fact_refs"]["items"]["enum"] == [fact["id"] for fact in packet["facts"]]
    assert props["operation_id"]["enum"] == [op["id"] for op in packet["operations"]] + [None]
    sent = json.loads(chat["messages"][1]["content"])
    assert sent["operations"] == packet["operations"] and "facts" in sent
    assert not ({"baseline", "runtime_hashes", "context_hash", "project_id"} & sent.keys())
    assert len(retry["messages"]) == len(chat["messages"]) + 1


@pytest.mark.parametrize("overrides", [
    {"inventory": []}, {"inventory": [False, {"name": "different-model", "digest": "x"}]},
    {"inventory": {"name": "broken inventory"}}, {"inventory": [{"name": "test-model"}]},
    {"model_info": {"remote_model": "remote"}}, {"model_info": {"remote_host": "https://remote.invalid"}},
    {"inventory": [{"name": "test-model", "digest": "model-sha", "remote_model": "remote"}]},
])
def test_uninstalled_or_remote_models_never_generate(monkeypatch, provider, packet, overrides):
    calls = local_ollama(monkeypatch, provider, **overrides)
    assert not provider.status()["available"]
    with pytest.raises(ProviderError, match="availability or identity"):
        provider.generate(packet, "model-sha")
    assert not any(path == "/api/chat" for path, _ in calls)


@pytest.mark.parametrize("port", ["", "11434/path", "-1", "0", "65536", "1" * 100])
def test_invalid_port_never_connects(monkeypatch, port):
    monkeypatch.setenv("FAILUREFORGE_OLLAMA_PORT", port)
    provider = LocalProvider()
    request = Mock(side_effect=AssertionError("Unexpected connection attempt"))
    monkeypatch.setattr(provider, "_request", request)
    assert not provider.status()["available"] and "valid local TCP port" in provider.status()["detail"]
    request.assert_not_called()


def test_offline_loopback_status_closes_connection(monkeypatch, provider):
    connection = Mock()
    connection.request.side_effect = ConnectionRefusedError
    constructor = Mock(return_value=connection)
    monkeypatch.setattr("failureforge.scenario_provider.http.client.HTTPConnection", constructor)
    status = provider.status()
    assert not status["available"] and "unavailable" in status["detail"]
    constructor.assert_called_once_with("127.0.0.1", 11434, timeout=3)
    connection.close.assert_called_once()


@pytest.mark.parametrize(("responses", "error"), [
    ([reply("[]"), reply("{}")], "schema validation twice"),
    ([reply("{}", done_reason="length"), reply("{}", done_reason="length")], "stopped before finishing"),
    ([reply("{}", done_reason="length", model="different-model")], "different model"),
    ([reply("{}", done=False)], "stopped before finishing"),
    ([reply("{}", model="different-model")], "different model"),
    ([reply("{}", remote_host="remote")], "different model"),
])
def test_failed_generation_does_not_return_a_synthetic_suggestion(monkeypatch, provider, packet, responses, error):
    calls = local_ollama(monkeypatch, provider, responses)
    with pytest.raises(ProviderError, match=error):
        provider.generate(packet, "model-sha")
    assert sum(path == "/api/chat" for path, _ in calls) == len(responses)


def test_provider_must_match_the_digest_recorded_at_generation_request(monkeypatch, provider, packet):
    calls = local_ollama(monkeypatch, provider)
    with pytest.raises(ProviderError, match="availability or identity"):
        provider.generate(packet, "old-sha")
    assert all(path != "/api/chat" for path, _ in calls)


def card(op=None, **changes):
    return {"title": "Part shifts when the operator moves it", "hypothesis": "A shift could affect deflection.",
            "operation_id": op, "fact_refs": ["task", "baseline.length_m"], "assumptions": [],
            "missing_capability": None if op else "A transient contact model", "question": None,
            "shift_ms": None, **changes}


def card_reply(candidates, questions=()):
    return reply(json.dumps({"candidates": candidates, "clarifications": list(questions)}))


def test_refine_once_adds_only_one_grounded_executable_to_the_originals(monkeypatch, provider, packet):
    first = card(title="Part bounces during transfer")
    executable = card("beam.load.tip_resultant", title="The part reaches the outer end")
    wrong_evidence = {**executable, "title": "Unsupported premise", "fact_refs": ["baseline.length_m"]}
    calls = local_ollama(monkeypatch, provider, [
        card_reply([first], ["Is a retaining feature present?"]),
        card_reply([card(), wrong_evidence, executable, {**executable, "title": "Alternate description"}]),
    ])
    batch, usage = provider.generate(packet, "model-sha")
    assert [c.title for c in batch.candidates] == [first["title"], executable["title"]]
    assert batch.clarifications == ["Is a retaining feature present?"]
    assert usage == {"attempts": 2, "prompt_tokens": 400, "output_tokens": 80, "refinement": "added"}
    original, refinement = [body for path, body in calls if path == "/api/chat"]
    assert refinement["options"]["num_predict"] < original["options"]["num_predict"]
    assert executable["operation_id"] in refinement["messages"][-1]["content"]


@pytest.mark.parametrize("second", [
    reply("{"), reply("{}", done=False), reply("{}", model="changed-model"),
    card_reply([], ["Can this use case occur?"]), card_reply([card("operation.not.available")]),
])
def test_refinement_can_decline_or_fail_without_displacing_first_ideas(monkeypatch, provider, packet, second):
    first = card()
    local_ollama(monkeypatch, provider, [card_reply([first]), second])
    batch, usage = provider.generate(packet, "model-sha")
    assert [c.model_dump() for c in batch.candidates] == [first] and usage["attempts"] == 2
    assert usage["refinement"] in {"unavailable", "no_executable_addition"}


def test_refinement_transport_failure_preserves_first_batch_and_marks_token_totals_unknown(monkeypatch, provider, packet):
    first = card()
    local_ollama(monkeypatch, provider, [card_reply([first])])
    request = provider._request
    sent = 0
    def interrupt_second_chat(path, *args, **kwargs):
        nonlocal sent
        if path == "/api/chat":
            sent += 1
            if sent == 2:
                raise ProviderError("The local model timed out.")
        return request(path, *args, **kwargs)
    monkeypatch.setattr(provider, "_request", interrupt_second_chat)
    batch, usage = provider.generate(packet, "model-sha")
    assert [c.model_dump() for c in batch.candidates] == [first] and sent == 2
    assert usage == {"attempts": 2, "prompt_tokens": None, "output_tokens": None, "refinement": "unavailable"}


def test_executable_first_batch_and_unloaded_reference_each_use_only_one_call(monkeypatch, provider, packet):
    executable = card("beam.load.tip_resultant")
    calls = local_ollama(monkeypatch, provider, [card_reply([executable])])
    batch, usage = provider.generate(packet, "model-sha")
    assert batch.candidates[0].model_dump() == executable
    assert usage["attempts"] == sum(path == "/api/chat" for path, _ in calls) == 1
    unloaded = copy.deepcopy(packet)
    unloaded["baseline"]["inputs"]["distributed_load_n_per_m"] = 0
    del unloaded["context_hash"]
    unloaded["context_hash"] = config_hash(unloaded)
    calls = local_ollama(monkeypatch, provider, [card_reply([card()])])
    _, usage = provider.generate(unloaded, "model-sha")
    assert usage["attempts"] == sum(path == "/api/chat" for path, _ in calls) == 1


def narrative(title, fact="baseline.length_m", **extra):
    return {"title": title, "hypothesis": "How the operator handles the part could change measured deflection.",
            "task_ref": "task", "evidence_ref": fact, "assumption": None, **extra}


def suite_reply(cases, untested=(), clarifications=()):
    return reply(json.dumps({"cases": cases, "untested": list(untested), "clarifications": list(clarifications)}))


@pytest.mark.parametrize("fixture", ["packet", "beam_packet"])
def test_truncation_retries_with_bounded_output_and_preserves_all_feasible_choices(
        monkeypatch, provider, request, fixture):
    context = request.getfixturevalue(fixture)
    first = card_reply([card(title="Discard even parseable truncated content")])
    first["done_reason"] = "length"
    accepted = card(context["operations"][-1]["id"], title="The operator changes the load position")
    calls = local_ollama(monkeypatch, provider, [first, card_reply([accepted])])
    batch, usage = provider.generate(context, "model-sha")
    assert [c.model_dump() for c in batch.candidates] == [accepted]
    assert usage == {"attempts": 2, "prompt_tokens": 400, "output_tokens": 80,
                     "retry_reason": "output_token_limit", "runnable_cases": 1}
    original, retry = [body for path, body in calls if path == "/api/chat"]
    schema = retry["format"]
    assert schema != original["format"] and schema["properties"]["candidates"]["maxItems"] == 2
    assert set(schema["$defs"]["CompactCandidate"]["properties"]["operation_id"]["enum"]) == {
        *(op["id"] for op in context["operations"]), None}
    assert "Discard even parseable" not in json.dumps(retry["messages"])


@pytest.mark.parametrize("second", [
    card_reply([card(), card(), card()]), card_reply([card("invented.operation")]),
    card_reply([card(fact_refs=["task", "made.up"])]), reply("{", done_reason="length"),
    reply("{}", model="replaced-model")
])
def test_invalid_truncation_retry_keeps_usage_and_returns_no_rows(monkeypatch, provider, beam_packet, second):
    calls = local_ollama(monkeypatch, provider, [reply("{", done_reason="length"), second])
    with pytest.raises(ProviderError) as failed:
        provider.generate(beam_packet, "model-sha")
    assert [path for path, _ in calls].count("/api/chat") == 2
    assert failed.value.usage["attempts"] == 2 and failed.value.usage["retry_reason"] == "output_token_limit"


def test_model_tag_replaced_between_chat_and_validation_discards_retry(monkeypatch, provider, packet):
    calls = local_ollama(monkeypatch, provider, [reply("{", done_reason="length"), card_reply([card()])])
    transport = provider._request

    def model_replaced(path, *args, **kwargs):
        result = transport(path, *args, **kwargs)
        if path == "/api/tags" and sum(p == "/api/chat" for p, _ in calls) == 2:
            result["models"][0]["digest"] = "other-sha"
        return result

    monkeypatch.setattr(provider, "_request", model_replaced)
    with pytest.raises(ProviderError, match="identity changed"):
        provider.generate(packet, "model-sha")


def test_registry_driven_generation_returns_five_distinct_measurable_cases(monkeypatch, provider, beam_packet):
    slots = _case_slots(beam_packet["operations"])
    assert len(slots) >= TARGET_CASES
    cases = {key: narrative(op["label"]) for key, op in slots.items()}
    untested = narrative("A part strikes the shelf", missing_effect="Transient impact response")
    calls = local_ollama(monkeypatch, provider, [suite_reply(cases, [untested])])
    batch, usage = provider.generate(beam_packet, "model-sha")
    assert usage["attempts"] == 1 and usage["runnable_cases"] == len(slots)
    identities, outcomes = set(), set()
    for draft in batch.candidates[:-1]:
        comparison = compile_candidate(beam_packet, draft, confirmed=True)
        assert comparison["state"] == "ready" and draft.fact_refs == ["task", "baseline.length_m"]
        identities.add(comparison["instance_hash"])
        result = run_job({**comparison["variant"], "assets": {}, "analysis_type": "structural"})
        outcomes.add(result["passed"])
    assert len(identities) == len(slots) and outcomes == {True, False}
    assert batch.candidates[-1].missing_capability == "Transient impact response"
    chat = next(body for path, body in calls if path == "/api/chat")
    assert chat["options"]["num_gpu"] == 0
    assert set(chat["format"]["properties"]["cases"]["properties"]) == set(slots)
    assert {s["operation"] for s in json.loads(chat["messages"][-1]["content"])["test_slots"].values()} == {
        op["id"] for op in beam_packet["operations"]}


def test_suite_refinement_keeps_first_ideas_and_only_offers_unfilled_slots(monkeypatch, provider, beam_packet):
    slots = _case_slots(beam_packet["operations"])
    first_key = next(iter(slots))
    first = {k: narrative("First proposal") if k == first_key else None for k in slots}
    remaining = {k: narrative(op["label"]) for k, op in slots.items() if k != first_key}
    untested = narrative("Dropped part", missing_effect="Transient contact")
    calls = local_ollama(monkeypatch, provider, [suite_reply(first, [untested]), suite_reply(remaining)])
    batch, usage = provider.generate(beam_packet, "model-sha")
    assert usage["attempts"] == 2 and usage["runnable_cases"] == len(slots)
    assert batch.candidates[0].title == "First proposal" and batch.candidates[-1].title == "Dropped part"
    _, second = [body for path, body in calls if path == "/api/chat"]
    assert set(second["format"]["properties"]["cases"]["properties"]) == set(remaining)


def test_suite_does_not_invent_cases_when_model_declines_or_cannot_refine(monkeypatch, provider, beam_packet):
    slots = _case_slots(beam_packet["operations"])
    first = {k: None for k in slots}
    first[next(iter(slots))] = narrative("The one proposed change")
    local_ollama(monkeypatch, provider, [suite_reply(first), reply("{")])
    batch, usage = provider.generate(beam_packet, "model-sha")
    assert usage["attempts"] == 2 and usage["runnable_cases"] == 1
    assert [c.title for c in batch.candidates] == ["The one proposed change"]


def test_suite_rejects_unknown_evidence_and_respects_repair_limit(monkeypatch, provider, beam_packet):
    cases = {k: narrative("Miscited case", "asset.invented") for k in _case_slots(beam_packet["operations"])}
    calls = local_ollama(monkeypatch, provider, [suite_reply(cases), suite_reply(cases)])
    with pytest.raises(ProviderError, match="schema validation twice"):
        provider.generate(beam_packet, "model-sha")
    assert [path for path, _ in calls].count("/api/chat") == 2


def test_timing_controls_count_once_per_actual_shift(monkeypatch, provider):
    project = {"id": "lift", "revision": 1, "analysis_type": "robot_behavior", "entry_stage": "prototype",
               "goal": "Raise the tray and engage the head", "success_criteria": "Hold at the target",
               "robot_source": "supported", "robot_template": "packaging_lift_v1"}
    inputs = {"payload_kg": .5, "head_force_n": 2}
    result = run_job({"adapter": "packaging_lift", "inputs": inputs, "assets": {}, "analysis_type": "robot_behavior"})
    evidence = {"inputs": inputs, "adapter": "packaging_lift", "snapshot": project, "runtime": {"test": "cpu"},
                "result": result}
    baseline = {**evidence, "project_id": project["id"], "project_revision": 1, "status": "completed",
                "id": "lift_ref", "evidence_hash": config_hash(evidence)}
    context = build_context(project, baseline, task="The press uses an independent clock.")
    slots = _case_slots(context["operations"])
    assert len(slots) == TARGET_CASES
    cases = {k: narrative("Press shift "+k, "baseline.head_force_n", shift_ms=-100) for k in slots}
    assert [op["shift_bounds_ms"] for op in slots.values()] == [
        [-1000, -801], [-800, -601], [-600, -401], [-400, -201], [-200, -1]]
    # All first responses choose a globally feasible shift, but -100 fits only slot five.
    remaining = {k: narrative("New shift "+k, "baseline.head_force_n", shift_ms=op["shift_bounds_ms"][0])
                 for k, op in list(slots.items())[:-1]}
    calls = local_ollama(monkeypatch, provider, [suite_reply(cases), suite_reply(remaining)])
    batch, usage = provider.generate(context, "model-sha")
    assert len({c.shift_ms for c in batch.candidates}) == usage["runnable_cases"] == TARGET_CASES
    assert {compile_candidate(context, c)["family_key"] for c in batch.candidates} == {"lift.press_timing"}
    assert next(c for c in batch.candidates if c.shift_ms == -100).title == "Press shift case_5"
    first, second = [body for path, body in calls if path == "/api/chat"]
    for slot, op in slots.items():
        field = first["format"]["properties"]["cases"]["properties"][slot]["anyOf"][0]["properties"]["shift_ms"]
        assert [field["minimum"], field["maximum"]] == op["shift_bounds_ms"]
    assert set(second["format"]["properties"]["cases"]["properties"]) == set(remaining)
    assert context["operations"][0]["shift_bounds_ms"] == [-1000, -1]


@pytest.mark.parametrize("lower,upper", [
    (-3, 2), (-1, 1), (-1, 1001), (-1001, 1), (-400, 600), (-6, -5), (3, 20), (10, 10)])
def test_timing_variations_cover_nonzero_feasible_domain_without_overlap(lower, upper):
    op = {"id": "variable-clock", "description": "Change the timing.", "shift_bounds_ms": [lower, upper]}
    slots = _case_slots([op])
    domain = [n for n in range(lower, upper + 1) if n]
    assert len(slots) == min(TARGET_CASES, len(domain))
    offered = []
    for slot in slots.values():
        low, high = slot["shift_bounds_ms"]
        assert low <= high and (high < 0 or low > 0)
        offered.extend(range(low, high + 1))
    assert offered == domain and op["shift_bounds_ms"] == [lower, upper]
