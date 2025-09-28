"""Tests for NaN value handling in Score serialization."""

import math

from inspect_ai._util.json import to_json_str_safe
from inspect_ai.scorer import Score


def test_score_can_have_nan_value():
    """Test that Score can serialize and deserialize NaN values correctly."""
    score = Score(value=math.nan)
    serialized = to_json_str_safe(score)
    deserialized = Score.model_validate_json(serialized)
    assert math.isnan(deserialized.value)
