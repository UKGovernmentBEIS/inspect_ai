import pytest

from inspect_ai._util.text import strip_numeric_punctuation


@pytest.mark.parametrize(
    "input_str,expected",
    [
        # Currency symbols and thousands separators are stripped: they are
        # value-preserving labels ("$20" denotes the quantity 20).
        ("$20", "20"),
        ("£20", "20"),
        ("€20", "20"),
        ("1,234", "1234"),
        # LLM formatting markers (markdown bold/italic) are also stripped.
        ("*20*", "20"),
        ("_20_", "20"),
        # The percent sign is deliberately NOT stripped.
        # Unlike the symbols above, "%" is a divide-by-100 operator:
        # "20%" is the quantity 0.2, not 20.
        # Stripping it to face value would make match(numeric=True)
        # both over- and under-count: a "20%" answer would score CORRECT
        # against target "20" for a question whose answer is 20 (false positive),
        # and a correct "60%" answer would score INCORRECT against
        # target "0.6" (false negative). Datasets that accept a percentage-
        # formatted answer should pass both forms as targets, e.g.
        # Target(["60", "60%"]), where the non-numeric "60%" is compared as a
        # string. This was settled in #838 / #939 and re-confirmed in #1622 /
        # #3782. Please don't add "%" to the strip set without revisiting that
        # discussion.
        ("20%", "20%"),
        ("60%", "60%"),
    ],
)
def test_strip_numeric_punctuation(input_str: str, expected: str) -> None:
    assert strip_numeric_punctuation(input_str) == expected
