"""Project-grounded scenario proposals and deterministic CPU experiment compilation."""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from math import fsum
from typing import Annotated, Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import config_hash
from .beam_span import load_profile, load_terms
from .packaging_lift import FIXTURE
from .project_bindings import binding_units
from .project_bundle import evidence as verify_run_evidence
from .project_runs import project_adapters
from .project_solver import MODELS, runtime_identity
from .project_validity import assessment_error


VERSION = "cpu-discovery-1"
TIMED_LIFT = "packaging_lift_timed_v2"
ShortText = Annotated[str, Field(min_length=1, max_length=320)]
Identifier = Annotated[str, Field(min_length=1, max_length=110)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class CandidateDraft(WireModel):
    title: Annotated[str, Field(min_length=1, max_length=120)]
    hypothesis: Annotated[str, Field(min_length=1, max_length=700)]
    operation_id: Identifier | None
    fact_refs: list[Identifier] = Field(min_length=1, max_length=12)
    assumptions: list[ShortText] = Field(max_length=6)
    missing_capability: ShortText | None
    question: ShortText | None
    shift_ms: Annotated[int, Field(ge=-2000, le=2000)] | None

    @model_validator(mode="after")
    def unique_refs(self):
        if len(set(self.fact_refs)) != len(self.fact_refs):
            raise ValueError("Duplicate evidence references")
        return self


class BatchDraft(WireModel):
    candidates: list[CandidateDraft] = Field(max_length=8)
    clarifications: list[ShortText] = Field(max_length=5)

    @model_validator(mode="after")
    def has_content(self):
        if not self.candidates and not self.clarifications:
            raise ValueError("Supply a grounded proposal or a clarification")
        return self


@dataclass(frozen=True)
class Operation:
    id: str
    family: str
    adapters: tuple[str, ...]
    execution_adapter: str
    label: str
    description: str
    observable: str
    compile: Callable
    unavailable_reason: Callable | None = None
    control_details: Callable | None = None

    def public(self, baseline):
        entry = {"id": self.id, "label": self.label, "description": self.description,
                 "observable": self.observable, "execution_adapter": self.execution_adapter}
        if self.control_details:
            entry.update(self.control_details(baseline))
        return entry


def _validated(adapter, inputs):
    raw = dict(inputs)
    if adapter == "structural_beam":
        raw.setdefault("kind", adapter)
    return MODELS[adapter].model_validate(raw)


class NeedsInformation(ValueError):
    """The project needs a different reference or an approved measurement rule."""


def _load_change_reason(baseline, layout):
    model = _validated("structural_beam", baseline["inputs"])
    terms = load_terms(model)
    forces = [f for _, _, f in terms]
    if not forces:
        return "Select a loaded reference to change its applied load."
    if layout and min(forces) < 0 < max(forces):
        return "Select a reference with nonzero transverse loads acting in one direction."
    total = fsum(forces)
    target = [(a, b, share*total) for a, b, share in layout]
    if load_profile(terms) == load_profile(target):
        return "This placement already has the same physical load distribution as the reference."
    return None


def _beam_placement(baseline, draft, *, layout):
    if draft.shift_ms is not None:
        raise ValueError("Load placement does not accept a timing change")
    model = _validated("structural_beam", baseline["inputs"])
    total = fsum(f for _, _, f in load_terms(model))
    unchanged = _load_change_reason(baseline, layout)
    if unchanged:
        raise ValueError(unchanged)
    measurements = []
    if model.max_displacement_m is not None:
        measurements.append(f"Maximum absolute deflection ≤ {model.max_displacement_m:g} m")
    if model.max_surface_stress_pa is not None:
        measurements.append(f"Maximum surface bending stress ≤ {model.max_surface_stress_pa:g} Pa")
    if not measurements:
        raise NeedsInformation("Set a deflection or stress limit in Analysis and complete a reference run.")
    reference = model.model_dump(exclude_none=True)
    variant = {**reference, "tip_force_n": 0., "distributed_load_n_per_m": 0.}
    for key in ("face_pressure_pa", "span_loads"):
        variant.pop(key, None)
    for a, b, share in layout:
        if a == b == 1:
            variant["tip_force_n"] = total*share
        elif a == 0 and b == 1:
            variant["distributed_load_n_per_m"] = total*share / model.length_m
        else:
            variant.setdefault("span_loads", []).append({"start_fraction": a, "end_fraction": b, "force_n": total*share})
    return reference, variant, measurements


def _effective_controls(adapter, inputs):
    """A point/patch distribution has one signature across equivalent input representations."""
    if adapter != "structural_beam":
        return inputs
    model = _validated(adapter, inputs)
    controls = model.model_dump(exclude={"face_pressure_pa", "span_loads"}, exclude_none=True)
    controls.update(tip_force_n=0., distributed_load_n_per_m=0.)
    for a, b, weight in load_profile(load_terms(model)):
        if a == b == 1:
            controls["tip_force_n"] = weight
        elif a == 0 and b == 1:
            controls["distributed_load_n_per_m"] = weight/model.length_m
        else:
            controls.setdefault("span_loads", []).append((a, b, weight))
    return controls


def _beam_operation(name, label, description, layout):
    """Fractions locate load support; each share multiplies the user's own signed resultant."""
    return Operation("beam.load." + name, "beam.load_placement" if layout else "beam.payload_removal",
                     ("structural_beam",), "structural_beam", label, description,
                     "Maximum deflection or surface bending stress", partial(_beam_placement, layout=layout),
                     partial(_load_change_reason, layout=layout))


def _timed_model(baseline):
    reference = dict(baseline["inputs"])
    if baseline["adapter"] == "packaging_lift":
        reference.update(head_onset_ms=1000, head_duration_ms=1000)
    return _validated(TIMED_LIFT, reference)


def _shift_bounds(model):
    earliest = -model.head_onset_ms
    latest = round(FIXTURE.end_time_s * 1000) - model.head_onset_ms - model.head_duration_ms
    return earliest if earliest else 1, latest if latest else -1


def _timing_unavailable(baseline):
    model = _timed_model(baseline)
    if not model.head_force_n:
        return "Select a reference with a nonzero, confirmed head force so timing has a physical effect."
    low, high = _shift_bounds(model)
    if low > high:
        return "The press spans the full cycle. Its onset cannot change while keeping its duration."
    return None


def _timing_controls(baseline):
    model = _timed_model(baseline)
    low, high = _shift_bounds(model)
    return {"shift_bounds_ms": [low, high],
            "description": f"Reference onset {model.head_onset_ms} ms, duration {model.head_duration_ms} ms. "
                           f"Choose a nonzero integer shift_ms between {low} and {high} inclusive. "
                           "Negative moves the press earlier; positive moves it later. Preserve duration, force, payload and deadline."}


def _timing(baseline, draft):
    if draft.shift_ms is None or draft.shift_ms == 0:
        raise NeedsInformation("Specify a nonzero signed onset shift in milliseconds.")
    unavailable = _timing_unavailable(baseline)
    if unavailable:
        raise NeedsInformation(unavailable)
    model = _timed_model(baseline)
    reference = model.model_dump()
    low, high = _shift_bounds(model)
    if not low <= draft.shift_ms <= high:
        raise ValueError("The shifted pulse must fit entirely inside the two-second cycle.")
    onset = model.head_onset_ms + draft.shift_ms
    measurements = [f"Arrival error at {FIXTURE.arrival_deadline_s:g} s ≤ {FIXTURE.error_limit_m:g} m",
                    f"Peak hold error from {FIXTURE.arrival_deadline_s:g} to {FIXTURE.end_time_s:g} s ≤ {FIXTURE.error_limit_m:g} m",
                    "Speed and travel within the fixture limits"]
    return reference, {**reference, "head_onset_ms": onset}, measurements


OPERATIONS = {
    op.id: op for op in (
        _beam_operation("tip_resultant", "Move the load to the free end",
                        "Place the same total transverse force at the free tip, opposite the clamp.", [(1., 1., 1.)]),
        _beam_operation("uniform_resultant", "Spread the load along the span",
                        "Spread the same total transverse force evenly along the full span.", [(0., 1., 1.)]),
        _beam_operation("midspan_point", "Concentrate the load at midspan",
                        "Place the same total force at one point halfway between the clamp and the free tip.", [(.5, .5, 1.)]),
        _beam_operation("inner_half_patch", "Load the half nearest the clamp",
                        "Spread the same total force uniformly over the inner half, from the clamp to midspan.", [(0., .5, 1.)]),
        _beam_operation("outer_half_patch", "Load the half nearest the free end",
                        "Spread the same total force uniformly over the outer half, from midspan to the free end.", [(.5, 1., 1.)]),
        _beam_operation("two_contacts", "Split the load across two contacts",
                        "Two localized contacts, at one-quarter and three-quarters of the span from the clamp, each carry half the same total force.",
                        [(.25, .25, .5), (.75, .75, .5)]),
        _beam_operation("remove_applied", "Remove the external load",
                        "Remove all applied transverse loads and measure the static unloaded equilibrium after pickup. Keep the mounting and material unchanged. Transient rebound and permanent deformation are outside this model.", []),
        Operation("lift.head.shift_onset", "lift.press_timing", ("packaging_lift", TIMED_LIFT), TIMED_LIFT,
                  "Shift the press earlier or later",
                  "Supply a nonzero signed shift_ms. Preserve press duration, force, payload and the arrival deadline. Both runs use the timed fixture.",
                  "Arrival and peak hold errors during the lift cycle", _timing, _timing_unavailable, _timing_controls),
    )
}


def build_context(project, baseline=None, task=""):
    """Project and run are server records. Send only this bounded projection to inference."""
    if len(task) > 2000:
        raise ValueError("Keep the scenario task under 2,000 characters.")
    facts = []
    excerpted = []

    def fact(identifier, label, value, source, unit="", *, limit=None):
        if limit and isinstance(value, str) and len(value) > limit:
            value = value[:limit]
            excerpted.append(identifier)
        facts.append({"id": identifier, "label": label, "value": value, "unit": unit, "source": source})

    fact("project.goal", "Intended job", project["goal"], "Saved project goal")
    fact("project.success_criteria", "Success criteria", project["success_criteria"], "Saved project requirement")
    if task.strip():
        fact("task", "Operating situation", task.strip(), "User-supplied discovery task")
    if project.get("notes"):
        fact("project.notes", "Design notes", project["notes"], "Saved project notes", limit=700)
    for i, p in enumerate(project.get("parameters", [])[:16]):
        fact(f"parameter.{i}", p["name"], p["value"],
             f"{p['source']} project parameter" + (f" — {p['evidence'][:100]}" if p.get("evidence") else ""), p["unit"], limit=160)
    for i, factor in enumerate(project.get("operating_factors", [])[:6]):
        fact(f"factor.{i}", factor["name"], factor["conditions"] or factor["name"],
             "Saved operating factor", factor["unit"], limit=160)
    for i, plan in enumerate(project.get("test_plans", [])[:4]):
        fact(f"plan.{i}", plan["name"], plan["objective"], "Saved project test plan", limit=200)
    for a in project.get("assets", [])[:8]:
        inspection = a.get("inspection") or {}
        details = inspection.get("details") or {}
        inventory = ", ".join(f"{k}={details[k]}" for k in ("links", "joints", "bodies", "missing_explicit_inertia") if k in details)
        fact(f"asset.{a['id']}", a["filename"], f"{a['kind']}. {inspection.get('summary', '')[:140]} {inventory}".strip(),
             f"Uploaded attachment SHA-256 {a['sha256']}")
    allowed = {a["id"] for a in project_adapters(project)}
    selected = None
    if baseline is not None:
        if baseline["project_id"] != project["id"] or baseline["project_revision"] != project["revision"]:
            raise ValueError("Select a reference belonging to this project and its current revision.")
        if (baseline["status"] != "completed" or not baseline.get("result") or not baseline.get("evidence_hash")
                or assessment_error(baseline["result"])):
            raise ValueError("Select a completed reference with valid numerical evidence.")
        verify_run_evidence(baseline)
        adapter = baseline["adapter"]
        if adapter not in allowed:
            raise ValueError("This reference adapter is unavailable for the selected prototype.")
        supported = any(adapter in op.adapters for op in OPERATIONS.values())
        # Unsupported adapters may contain nested controller targets or uploaded IDs.
        # Planning needs their identity, not an unrelated controller configuration.
        inputs = _validated(adapter, baseline["inputs"]).model_dump(exclude_none=True) if supported else {}
        selected = {"run_id": baseline["id"], "adapter": adapter, "inputs": inputs,
                    "evidence_hash": baseline["evidence_hash"]}
        unit_table = binding_units(adapter, project["analysis_type"])
        for field, value in inputs.items():
            if type(value) in (int, float):
                evidence = (baseline.get("binding_evidence") or {}).get(field)
                source = f"Reference run {baseline['id']}"
                if evidence:
                    source += f", bound to {evidence['parameter_name']} ({evidence['source_value']} {evidence['source_unit']})"
                fact("baseline." + field, field, value, source, unit_table.get(field, "ms" if field.endswith("_ms") else ""))
        for i, load in enumerate(inputs.get("span_loads") or (), 1):
            for name, value in load.items():
                fact(f"baseline.span_loads.{i}.{name}", f"Span load {i} {name}", value,
                     f"Selected reference run {baseline['id']}", "N" if name == "force_n" else "1")
        fact("baseline.adapter", "Reference model", adapter, f"Selected reference run {baseline['id']}")
    operations = []
    for op in OPERATIONS.values():
        if (op.execution_adapter in allowed and selected and selected["adapter"] in op.adapters
                and not (op.unavailable_reason and op.unavailable_reason(selected))):
            operations.append(op.public(selected))
    omitted = {key: len(project.get(key, [])) - limit for key, limit in (
        ("assets", 8), ("parameters", 16), ("operating_factors", 6), ("test_plans", 4)) if len(project.get(key, [])) > limit}
    packet = {"version": VERSION, "project_id": project["id"], "revision": project["revision"],
              "stage": project["entry_stage"], "analysis_type": project["analysis_type"],
              "facts": facts, "operations": operations, "baseline": selected,
              "omitted_records": omitted, "excerpted_fact_ids": excerpted}
    packet["runtime_hashes"] = {adapter: config_hash(runtime_identity(adapter))
                                for adapter in sorted({op["execution_adapter"] for op in operations})}
    packet["context_hash"] = config_hash(packet)
    return packet


def compile_candidate(context, draft: CandidateDraft, confirmed=False):
    """Compile only server-declared control changes; no text is interpreted as solver input."""
    facts = {f["id"]: f for f in context["facts"]}
    op = OPERATIONS.get(draft.operation_id)
    baseline = context["baseline"]
    family = op.family if op else None
    report = {"facts": [facts[ref] for ref in draft.fact_refs if ref in facts], "family_key": family,
              "observables": [], "reference": None, "variant": None, "diff": {}, "instance_hash": None}

    def finish(state, reason):
        fingerprint = config_hash({"version": VERSION, "context": context["context_hash"], "review": draft.model_dump(),
                                   "compiled": report["instance_hash"], "confirmed": confirmed})
        return {**report, "state": state, "reason": reason, "fingerprint": fingerprint}

    if (context["version"] != VERSION
            or config_hash({k: v for k, v in context.items() if k != "context_hash"}) != context["context_hash"]):
        return finish("invalid", "The saved project context changed. Generate a new review for this revision.")
    if any(ref not in facts for ref in draft.fact_refs):
        return finish("invalid", "The suggestion cites evidence outside the selected project context.")
    if draft.missing_capability:
        return finish("needs_capability", "The proposed situation cannot be compiled in full with the registered operations for this reference.")
    if draft.operation_id and op is None:
        return finish("invalid", "The proposed operation is absent from the simulator capability registry.")
    if not baseline:
        return finish("needs_information", "Select a completed reference run for this project revision to preview an executable case.")
    if op is None:
        return finish("needs_information" if draft.question else "needs_capability",
                      draft.question or "The selected model has no executable operation for this mechanism.")
    if op.id not in {entry["id"] for entry in context["operations"]}:
        if baseline["adapter"] in op.adapters and op.unavailable_reason:
            why = op.unavailable_reason(baseline)
            if why:
                return finish("invalid", why)
        return finish("needs_capability", "The selected model cannot apply this operation.")
    try:
        reference, variant, observables = op.compile(baseline, draft)
        _validated(op.execution_adapter, reference)
        _validated(op.execution_adapter, variant)
    except NeedsInformation as exc:
        return finish("needs_information", str(exc))
    except ValueError as exc:
        return finish("invalid", str(exc)[:600])
    report["reference"] = {"label": "Reference condition", "adapter": op.execution_adapter, "inputs": reference}
    report["variant"] = {"label": op.label, "adapter": op.execution_adapter, "inputs": variant}
    report["diff"] = {k: {"reference": reference.get(k), "variant": variant.get(k)}
                      for k in sorted(reference.keys() | variant.keys()) if reference.get(k) != variant.get(k)}
    report["observables"] = observables
    report["instance_hash"] = config_hash({"adapter": op.execution_adapter,
                                          "reference": _effective_controls(op.execution_adapter, reference),
                                          "variant": _effective_controls(op.execution_adapter, variant), "version": VERSION})
    if not confirmed:
        reason = "Review the exact reference, changed controls and assumptions. Confirm that this test represents the proposed situation."
        if baseline["adapter"] != op.execution_adapter:
            reason += " Both cases use the timed fixture; the reference recreates the original one-second hold press."
        return finish("needs_information", reason)
    return finish("ready", "The selected model supports this reviewed comparison.")
