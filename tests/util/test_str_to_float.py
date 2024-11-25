import pytest

from inspect_ai._util.text import str_to_float


def test_str_to_float_basic():
    assert str_to_float("1²") == 1.0
    assert str_to_float("2³") == 8.0
    assert str_to_float("5⁴") == 625.0
    assert str_to_float("10⁰") == 1.0
    assert str_to_float("3") == 3.0


def test_str_to_float_decimal_base():
    assert str_to_float("2.5²") == 2.5**2
    assert str_to_float("0.1³") == 0.1**3


def test_str_to_float_negative_base():
    assert str_to_float("-2²") == (-2) ** 2
    assert str_to_float("-2³") == (-2) ** 3


def test_str_to_float_multi_digit_exponent():
    assert str_to_float("2⁴⁵") == 2**45
    assert str_to_float("3⁰⁰⁰") == 3**0  # Exponent is 0


def test_str_to_float_no_exponent():
    assert str_to_float("7") == 7.0
    assert str_to_float("0") == 0.0


def test_str_to_float_no_base():
    # When the base is missing, default to 1.0
    assert str_to_float("⁵") == 1.0**5
    assert str_to_float("⁰") == 1.0**0


def test_str_to_float_zero_exponent():
    assert str_to_float("5⁰") == 1.0
    assert str_to_float("0⁰") == 1.0  # 0^0 is considered 1 in this context


def test_str_to_float_invalid_input():
    with pytest.raises(ValueError):
        str_to_float("abc")
    with pytest.raises(ValueError):
        str_to_float("")
    with pytest.raises(ValueError):
        str_to_float("2^3")
    with pytest.raises(ValueError):
        str_to_float("⁺²")  # Unsupported superscript characters


def test_str_to_float_edge_cases():
    # Exponent with unsupported characters
    with pytest.raises(ValueError):
        str_to_float("2⁻³")
    # Base with unsupported characters
    with pytest.raises(ValueError):
        str_to_float("a²")
    # Superscript after decimal point
    assert str_to_float("2.5⁴") == 2.5**4
