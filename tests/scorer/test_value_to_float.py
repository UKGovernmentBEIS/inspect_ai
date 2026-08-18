import math

from inspect_ai.scorer import CORRECT, PARTIAL, value_to_float


def test_value_to_float_numbers():
    fn = value_to_float()
    assert fn(1) == 1.0
    assert fn(0.5) == 0.5
    assert fn(True) == 1.0
    assert fn(False) == 0


def test_value_to_float_strings():
    fn = value_to_float()
    assert fn("1.0") == 1.0
    assert fn("0.5") == 0.5
    assert fn("0") == 0
    assert fn("yes") == 1.0
    assert fn("No") == 0.0
    assert fn(CORRECT) == 1.0
    assert fn(PARTIAL) == 0.5


def test_value_to_float_custom():
    fn = value_to_float(correct="correct", incorrect="incorrect")
    assert fn("correct") == 1.0
    assert fn("incorrect") == 0


def test_value_to_float_custom_numeric():
    # Regression: numeric custom values were cast to float and passed through
    # instead of being mapped, silently corrupting downstream metrics (e.g.
    # accuracy() could go negative or above 1). The docstring explicitly
    # allows customizing the correct/incorrect/partial/noanswer values, and
    # the Value type allows numeric literals.
    fn = value_to_float(correct=2.0, incorrect=0.0, partial=1.0)
    assert fn(2.0) == 1.0
    assert fn(1.0) == 0.5
    assert fn(0.0) == 0.0

    fn = value_to_float(correct=1, incorrect=-1)
    assert fn(1) == 1.0
    assert fn(-1) == 0.0

    fn = value_to_float(partial=True)
    assert fn(True) == 0.5

    # int/float cross-type sentinel equality (2 == 2.0)
    fn = value_to_float(correct=2.0)
    assert fn(2) == 1.0

    # non-sentinel numerics must still pass through unchanged
    fn = value_to_float(correct=1, incorrect=-1)
    assert fn(3) == 3.0
    assert fn(0.5) == 0.5


def test_value_to_float_non_finite_numeric_passthrough():
    # Regression (#4580): non-finite numeric values must keep passing
    # through — they never compare equal to any sentinel value, so mapping
    # checks placed before the numeric cast don't affect them.
    fn = value_to_float()
    assert math.isnan(fn(float("nan")))
    assert math.isinf(fn(float("inf")))
    assert math.isinf(fn(float("-inf")))

    # also under custom numeric sentinels — nan/inf never equal any sentinel
    fn = value_to_float(correct=1, incorrect=-1)
    assert math.isnan(fn(float("nan")))
    assert math.isinf(fn(float("inf")))


def test_value_to_float_invalid():
    fn = value_to_float()
    assert fn("foo") == 0.0


def test_value_to_float_non_finite_strings():
    # Regression: float("nan") / float("inf") don't raise, so these strings
    # were converted to non-finite floats and poisoned downstream metrics
    # (e.g. one Score(value="nan") made accuracy() return NaN). They should
    # fall through to the unrecognised-string path and return 0.0.
    fn = value_to_float()
    assert fn("nan") == 0.0
    assert fn("NaN") == 0.0
    assert fn("inf") == 0.0
    assert fn("-inf") == 0.0
