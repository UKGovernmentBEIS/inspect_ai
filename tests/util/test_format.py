"""Tests for format_progress_time() and display_safe()."""

import pytest

from inspect_ai._util.format import display_safe, format_progress_time


def test_progress_time_whole_seconds() -> None:
    assert format_progress_time(0.0) == " 0:00:00"
    assert format_progress_time(5.0) == " 0:00:05"
    assert format_progress_time(60.0) == " 0:01:00"
    assert format_progress_time(3600.0) == " 1:00:00"
    assert format_progress_time(3661.0) == " 1:01:01"


def test_progress_time_truncates_fractional_seconds() -> None:
    # A fractional component must be truncated, not rounded: the ".0f" spec used
    # to round 59.9 up to ":60", which a clock can never legitimately show.
    assert format_progress_time(59.9) == " 0:00:59"
    assert format_progress_time(3599.9) == " 0:59:59"
    assert format_progress_time(3659.9) == " 1:00:59"


def test_progress_time_no_pad_hours() -> None:
    assert format_progress_time(0.0, pad_hours=False) == "0:00:00"
    assert format_progress_time(59.9, pad_hours=False) == "0:00:59"
    assert format_progress_time(3661.0, pad_hours=False) == "1:01:01"


def test_progress_time_hours_not_truncated_to_two_digits() -> None:
    assert format_progress_time(36000.0) == "10:00:00"


# a backslash, kept out of string literals so each test reads as what it shows
BS = chr(92)


@pytest.mark.parametrize(
    "code, shown",
    [
        # C0 controls, at both ends and the carriage return's own escape
        (0x00, "x00"),
        (0x08, "x08"),
        (0x0B, "x0b"),
        (0x0D, "r"),
        (0x1B, "x1b"),
        (0x1F, "x1f"),
        # DEL and the C1 controls, 8-bit CSI among them
        (0x7F, "x7f"),
        (0x80, "x80"),
        (0x9B, "x9b"),
        (0x9F, "x9f"),
        # zero-width characters and the word joiner
        (0x200B, "u200b"),
        (0x200D, "u200d"),
        (0x2060, "u2060"),
        # bidi embeddings, overrides and isolates
        (0x202A, "u202a"),
        (0x202E, "u202e"),
        (0x2066, "u2066"),
        (0x2069, "u2069"),
        # zero-width no-break space
        (0xFEFF, "ufeff"),
        # the tag block
        (0xE0000, "U000e0000"),
        (0xE0041, "U000e0041"),
        (0xE007F, "U000e007f"),
    ],
)
def test_display_safe_shows_each_unsafe_character_as_an_escape(
    code: int, shown: str
) -> None:
    assert display_safe(f"a{chr(code)}b") == (f"a{BS}{shown}b", True)


@pytest.mark.parametrize(
    "code",
    [
        0x09,  # tab
        0x0A,  # newline
        0x20,  # after the C0 controls
        0x7E,  # before DEL
        0xA0,  # after the C1 controls
        0x200A,  # before the zero-width characters
        0x200E,  # a bidi mark, not an override
        0x2028,  # line separator
        0xE0080,  # after the tag block
        0xE9,  # e with an acute accent
    ],
)
def test_display_safe_keeps_other_characters(code: int) -> None:
    assert display_safe(f"a{chr(code)}b") == (f"a{chr(code)}b", False)


def test_display_safe_leaves_plain_text_alone() -> None:
    text = f"echo {BS}x1b && printf '{BS}n'\n\tdone"
    assert display_safe(text) == (text, False)


def test_display_safe_escapes_backslashes_once_anything_is_escaped() -> None:
    # typed text that looks like an escape, beside a real escape character
    typed = f"{BS}x1b"
    shown = display_safe(f"{typed}{chr(0x1B)}")
    assert shown == (f"{BS}{BS}x1b{BS}x1b", True)
