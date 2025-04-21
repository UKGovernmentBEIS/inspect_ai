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


def test_str_to_float_unicode_fractions():
    # Test simple fraction characters
    assert str_to_float("½") == 0.5
    assert str_to_float("¼") == 0.25
    assert str_to_float("¾") == 0.75
    assert str_to_float("⅓") == 1 / 3
    assert str_to_float("⅔") == 2 / 3

    # Test more complex fractions
    assert str_to_float("⅛") == 0.125
    assert str_to_float("⅜") == 0.375
    assert str_to_float("⅝") == 0.625
    assert str_to_float("⅞") == 0.875


def test_str_to_float_mixed_fractions():
    # Whole number with fraction
    assert str_to_float("2½") == 2.5
    assert str_to_float("1¾") == 1.75
    assert str_to_float("3⅓") == 3 + (1 / 3)

    # Negative number with fraction
    assert str_to_float("-2½") == -2.5
    assert str_to_float("-1¼") == -1.25


def test_str_to_float_mixed_fractions_with_exponents():
    # Fraction with exponent
    assert str_to_float("½²") == 0.5**2
    assert str_to_float("¾³") == 0.75**3

    # Fraction with multi-digit exponents
    assert str_to_float("½²³") == 0.5**23  # Interpreted as 0.5^23, not (0.5^2)^3
    assert str_to_float("¾³²") == 0.75**32  # Interpreted as 0.75^32, not (0.75^3)^2

    # Whole number, fraction, and exponent
    assert str_to_float("2½²") == 2.5**2
    assert str_to_float("1¾³") == 1.75**3

    # Negative number with fraction and exponent
    assert str_to_float("-2½²") == (-2.5) ** 2
    assert str_to_float("-1¼³") == (-1.25) ** 3


def test_str_to_float_fraction_invalid_input():
    # Multiple fraction characters
    with pytest.raises(ValueError):
        str_to_float("½¾")

    # Invalid character before fraction
    with pytest.raises(ValueError):
        str_to_float("a½")

    # Invalid character between number and fraction
    with pytest.raises(ValueError):
        str_to_float("2a½")
