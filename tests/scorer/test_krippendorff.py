import math
from unittest.mock import patch

import pytest

from inspect_ai.scorer import Score, krippendorff_alpha, value_to_float
from inspect_ai.scorer._metric import SampleScore


def _nominal_warning_emitted(mock_logger) -> bool:
    return any(
        call.args and "nominal level applied to numeric data" in call.args[0]
        for call in mock_logger.warning.call_args_list
    )


def _sample_scores(units):
    return [SampleScore(score=Score(value=u)) for u in units]


# ---------------------------------------------------------------------------
# nominal
# ---------------------------------------------------------------------------


def test_krippendorff_perfect_agreement():
    alpha = krippendorff_alpha()
    assert alpha(_sample_scores([[1, 1, 1], [0, 0, 0], [1, 1, 1]])) == 1.0


def test_krippendorff_systematic_disagreement():
    # 4 samples, 2 judges, judges always disagree, overall counts balanced.
    # D_o = 1.0, D_e = 4/7, alpha = 1 - 7/4 = -0.75
    alpha = krippendorff_alpha()
    assert alpha(_sample_scores([[0, 1], [0, 1], [1, 0], [1, 0]])) == -0.75


def test_krippendorff_known_value():
    # 4 samples x 3 raters; one off-rating in the last sample.
    # D_o = 1/6, D_e = 70/132, alpha = 1 - 132/420 = 0.685714...
    alpha = krippendorff_alpha()
    result = alpha(_sample_scores([[1, 1, 1], [0, 0, 0], [1, 1, 1], [0, 0, 1]]))
    assert math.isclose(result, 1.0 - 132.0 / 420.0, rel_tol=0, abs_tol=1e-12)


def test_krippendorff_two_judge_perfect_agreement():
    alpha = krippendorff_alpha()
    assert alpha(_sample_scores([["a", "a"], ["b", "b"], ["c", "c"]])) == 1.0


def test_krippendorff_empty_returns_nan():
    assert math.isnan(krippendorff_alpha()([]))


def test_krippendorff_all_identical_values_returns_one():
    # When every rating is the same value, D_e = 0 (nothing to disagree about).
    # The metric should return 1.0 via the d_e == 0 / d_o == 0 special case
    # rather than nan from a 0/0 division.
    alpha = krippendorff_alpha()
    assert alpha(_sample_scores([[5, 5], [5, 5], [5, 5]])) == 1.0


def test_krippendorff_skips_non_sequence_values():
    alpha = krippendorff_alpha()
    scores = [
        SampleScore(score=Score(value=1)),
        SampleScore(score=Score(value=[1, 1, 1])),
        SampleScore(score=Score(value=[0, 0, 0])),
    ]
    assert alpha(scores) == 1.0


def test_krippendorff_uneven_raters():
    # Sample 1: 3 raters; Sample 2: 2 raters.
    # D_o = 2/5 = 0.4, D_e = 0.6, alpha = 1/3.
    alpha = krippendorff_alpha()
    result = alpha(_sample_scores([[1, 1, 0], [0, 0]]))
    assert math.isclose(result, 1.0 / 3.0, rel_tol=0, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# interval
# ---------------------------------------------------------------------------


def test_krippendorff_interval_known_value():
    # values [1,2,3,4,1,1] across 3 samples of 2 raters each.
    # D_o = 2/3, D_e = 16/5, alpha = 19/24
    alpha = krippendorff_alpha(level="interval")
    result = alpha(_sample_scores([[1.0, 2.0], [3.0, 4.0], [1.0, 1.0]]))
    assert math.isclose(result, 19.0 / 24.0, rel_tol=0, abs_tol=1e-12)


def test_krippendorff_interval_coerces_int_to_float():
    alpha = krippendorff_alpha(level="interval")
    assert alpha(_sample_scores([[1, 1], [2, 2], [3, 3]])) == 1.0


def test_krippendorff_interval_with_to_float_for_strings():
    alpha = krippendorff_alpha(level="interval", to_float=value_to_float())
    assert alpha(_sample_scores([["C", "C"], ["I", "I"]])) == 1.0


def test_krippendorff_interval_string_without_to_float_raises():
    alpha = krippendorff_alpha(level="interval")
    with pytest.raises(ValueError, match="non-numeric rating"):
        alpha(_sample_scores([["low", "low"], ["high", "high"]]))


# ---------------------------------------------------------------------------
# ordinal
# ---------------------------------------------------------------------------


def test_krippendorff_ordinal_known_value():
    # 3 samples x 2 raters on a 1-5 Likert scale.
    # Marginal counts: {1: 2, 3: 1, 4: 1, 5: 2}.
    # D_o = 1/3, D_e = 33/5, alpha = 1 - 5/99 = 94/99.
    alpha = krippendorff_alpha(level="ordinal")
    result = alpha(_sample_scores([[1, 1], [3, 4], [5, 5]]))
    assert math.isclose(result, 94.0 / 99.0, rel_tol=0, abs_tol=1e-12)


def test_krippendorff_ordinal_perfect_agreement():
    alpha = krippendorff_alpha(level="ordinal")
    assert alpha(_sample_scores([[1, 1, 1], [3, 3, 3], [5, 5, 5]])) == 1.0


def test_krippendorff_ordinal_diverges_from_interval_on_skewed_data():
    # Skewed distribution (heavy at 4-5, sparse at 1) — ordinal and interval
    # weight the (1 vs 5) and (4 vs 5) disagreements differently.
    data = [[1, 1, 5], [5, 5, 5], [4, 5, 5], [4, 4, 5]]
    ordinal = krippendorff_alpha(level="ordinal")(_sample_scores(data))
    interval = krippendorff_alpha(level="interval")(_sample_scores(data))
    assert not math.isclose(ordinal, interval, rel_tol=0, abs_tol=0.05)


def test_krippendorff_ordinal_with_to_float_for_text_categories():
    ordering = {"low": 0.0, "medium": 1.0, "high": 2.0}
    alpha = krippendorff_alpha(level="ordinal", to_float=lambda v: ordering[v])
    data = [["low", "low"], ["medium", "medium"], ["high", "high"]]
    assert alpha(_sample_scores(data)) == 1.0


def test_krippendorff_ordinal_text_without_to_float_raises():
    alpha = krippendorff_alpha(level="ordinal")
    with pytest.raises(ValueError, match="non-numeric rating"):
        alpha(_sample_scores([["low", "low"], ["high", "high"]]))


# ---------------------------------------------------------------------------
# footgun mitigations
# ---------------------------------------------------------------------------


def test_krippendorff_nominal_on_numeric_warns():
    alpha = krippendorff_alpha()
    with patch("inspect_ai.scorer._metrics.krippendorff.logger") as mock_logger:
        alpha(_sample_scores([[1, 1], [3, 3], [5, 5]]))
    assert _nominal_warning_emitted(mock_logger)


def test_krippendorff_nominal_on_binary_does_not_warn():
    alpha = krippendorff_alpha()
    with patch("inspect_ai.scorer._metrics.krippendorff.logger") as mock_logger:
        alpha(_sample_scores([[0, 1], [1, 1], [0, 0]]))
    assert not _nominal_warning_emitted(mock_logger)


def test_krippendorff_nominal_on_strings_does_not_warn():
    alpha = krippendorff_alpha()
    with patch("inspect_ai.scorer._metrics.krippendorff.logger") as mock_logger:
        alpha(_sample_scores([["a", "a"], ["b", "b"], ["c", "c"]]))
    assert not _nominal_warning_emitted(mock_logger)


def test_krippendorff_invalid_level_raises():
    with pytest.raises(ValueError, match="unsupported level"):
        krippendorff_alpha(level="ratio")
