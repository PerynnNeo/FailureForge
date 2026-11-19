import math

import pytest
from hypothesis import given, strategies as st
from pydantic import ValidationError

from failureforge.contracts import CampaignSpec, Domain, SceneChange, config_hash


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -0.041, 0.041])
def test_scene_rejects_nonfinite_or_unapproved_displacement(value):
    with pytest.raises(ValidationError):
        SceneChange(main_camera_dx_m=value)


@given(st.floats(min_value=-0.04, max_value=0), st.floats(min_value=0, max_value=0.04))
def test_valid_domains_roundtrip(low, high):
    if high - low < 1e-8:
        with pytest.raises(ValidationError):
            Domain(main_camera_dx_m=(low, high))
        return
    model = Domain(main_camera_dx_m=(low, high))
    assert Domain.model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize("kwargs", [{"state_ids": [0, 0]}, {"state_ids": [0, 2]}, {"state_ids": [True, 1]}, {"candidate_count": 3}, {"seed": 0.5}, {"checkpoint": "arbitrary-model"}])
def test_experiment_contract_rejects_ambiguous_or_unsupported_input(kwargs):
    with pytest.raises(ValidationError):
        CampaignSpec(**kwargs)


def test_spec_hash_is_order_independent_and_rejects_nonfinite():
    assert config_hash({"b": 1, "a": 2}) == config_hash({"a": 2, "b": 1})
    with pytest.raises(ValueError):
        config_hash({"x": math.nan})


def test_domain_cannot_exclude_reference_or_exceed_catalog():
    for values in [(0.01, 0.03), (-0.05, 0.04), (0, 0), (-1e-12, 1e-12)]:
        with pytest.raises(ValidationError):
            Domain(main_camera_dx_m=values)
    with pytest.raises(ValidationError):
        Domain(light_scale=(1 - 1e-12, 1 + 1e-12))
