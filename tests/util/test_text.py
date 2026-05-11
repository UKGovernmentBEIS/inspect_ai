import pytest

from inspect_ai._util.text import strip_numeric_punctuation


@pytest.mark.parametrize(
    "input_str,expected",
    [
        # percent suffix (the fix)
        ("20%", "20"),
        ("50%", "50"),
        ("60.5%", "60.5"),
        # currency symbols
        ("$42", "42"),
        ("£42", "42"),
        ("€100", "100"),
        # thousands separator
        ("$1,234", "1234"),
        ("1,234,567", "1234567"),
        # decimal point: preserved when followed by a digit, stripped otherwise
        ("3.14", "3.14"),
        ("3.", "3"),
        ("3. ", "3 "),
        # LLM-added formatting markers
        ("*100*", "100"),
        ("_42_", "42"),
        # combinations
        ("$1,234.56", "1234.56"),
        ("**60.5%**", "60.5"),
        # no-op for plain text and empty input
        ("plain text", "plain text"),
        ("", ""),
    ],
)
def test_strip_numeric_punctuation(input_str: str, expected: str) -> None:
    assert strip_numeric_punctuation(input_str) == expected
