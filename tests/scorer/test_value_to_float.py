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


def test_value_to_float_invalid():
    fn = value_to_float()
    assert fn("foo") == 0.0
