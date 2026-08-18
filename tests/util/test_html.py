"""Tests for as_html_id()."""

from inspect_ai._util.html import as_html_id


def test_empty_text_is_prefixed() -> None:
    # empty ids are invalid HTML, so fall back to the prefix
    assert as_html_id("id", "") == "id-"


def test_symbol_only_text_passthrough() -> None:
    # non-alnum chars become dashes; non-empty result is left as-is, not prefixed
    assert as_html_id("id", "***") == "---"


def test_digit_start_is_prefixed() -> None:
    # ids may not start with a digit
    assert as_html_id("id", "3options") == "id-3options"


def test_normal_text_is_lowercased_and_dashed() -> None:
    assert as_html_id("id", "Hello World") == "hello-world"


def test_already_valid_passthrough() -> None:
    assert as_html_id("id", "abc") == "abc"
