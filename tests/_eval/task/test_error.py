import pytest

from inspect_ai._eval.task.error import _should_eval_fail


@pytest.mark.parametrize(
    "sample_error_count,total_sample_count,fail_on_error,expected",
    [
        (0, 100, False, False),
        (1, 100, False, False),
        (999, 100, False, False),
    ],
)
def test_fail_on_error_false_never_fails(
    sample_error_count, total_sample_count, fail_on_error, expected
):
    assert (
        _should_eval_fail(sample_error_count, total_sample_count, fail_on_error)
        is expected
    )


@pytest.mark.parametrize("fail_on_error", [None, True])
@pytest.mark.parametrize(
    "sample_error_count,total_sample_count,expected",
    [
        (0, 100, False),
        (1, 100, True),
        (5, 100, True),
    ],
)
def test_fail_on_error_none_or_true_fails_if_any_error(
    sample_error_count, total_sample_count, fail_on_error, expected
):
    assert (
        _should_eval_fail(sample_error_count, total_sample_count, fail_on_error)
        is expected
    )


@pytest.mark.parametrize(
    "sample_error_count,total_sample_count,fail_on_error,expected",
    [
        (0, 10, 0.1, False),  # threshold 0.1  -> 0 OK,
        (1, 10, 0.1, True),  #                   1 fails
        (2, 10, 0.25, False),  # threshold 0.25 -> 2 OK,
        (3, 10, 0.25, True),  #                   3 fails
        (3, 8, 0.5, False),  # threshold 0.5  -> 3 OK,
        (4, 8, 0.5, True),  #                   4 fails
        (98, 100, 0.99, False),  # threshold 0.99 -> 98 OK,
        (99, 100, 0.99, True),  #                   99 fails
    ],
)
def test_fractional_rate_thresholds(
    sample_error_count, total_sample_count, fail_on_error, expected
):
    assert (
        _should_eval_fail(sample_error_count, total_sample_count, fail_on_error)
        is expected
    )


@pytest.mark.parametrize(
    "sample_error_count,total_sample_count,fail_on_error,expected",
    [
        (0, 100, 1, False),
        (1, 100, 1, True),
        (2, 5, 3, False),
        (3, 5, 3, True),
        (10, 0, 3, True),
    ],
)
def test_absolute_count_thresholds(
    sample_error_count, total_sample_count, fail_on_error, expected
):
    assert (
        _should_eval_fail(sample_error_count, total_sample_count, fail_on_error)
        is expected
    )
