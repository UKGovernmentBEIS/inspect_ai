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


# the marker around a code point, kept out of string literals so each test
# reads as what it shows
OPEN, CLOSE = chr(0x2039), chr(0x203A)


def marker(code: str) -> str:
    return f"{OPEN}U+{code}{CLOSE}"


@pytest.mark.parametrize(
    "code, shown",
    [
        # C0 controls, at both ends of each range
        (0x00, "0000"),
        (0x08, "0008"),
        (0x0B, "000B"),
        (0x0D, "000D"),
        (0x1B, "001B"),
        (0x1F, "001F"),
        # DEL and the C1 controls, 8-bit CSI among them
        (0x7F, "007F"),
        (0x80, "0080"),
        (0x9B, "009B"),
        (0x9F, "009F"),
        # zero-width characters and the word joiner
        (0x200B, "200B"),
        (0x200D, "200D"),
        (0x2060, "2060"),
        # bidi embeddings, overrides and isolates
        (0x202A, "202A"),
        (0x202E, "202E"),
        (0x2066, "2066"),
        (0x2069, "2069"),
        # zero-width no-break space
        (0xFEFF, "FEFF"),
        # the tag block
        (0xE0000, "E0000"),
        (0xE0041, "E0041"),
        (0xE007F, "E007F"),
        # the marker's own opening character
        (0x2039, "2039"),
    ],
)
def test_display_safe_shows_each_unsafe_character_as_a_marker(
    code: int, shown: str
) -> None:
    assert display_safe(f"a{chr(code)}b") == (f"a{marker(shown)}b", True)


@pytest.mark.parametrize(
    "code",
    [
        0x09,  # tab
        0x0A,  # newline
        0x20,  # after the C0 controls
        0x5C,  # backslash
        0x7E,  # before DEL
        0xA0,  # after the C1 controls
        0x200A,  # before the zero-width characters
        0x200E,  # a bidi mark, not an override
        0x2028,  # line separator
        0x203A,  # the marker's closing character
        0xE0080,  # after the tag block
        0xE9,  # e with an acute accent
    ],
)
def test_display_safe_keeps_other_characters(code: int) -> None:
    assert display_safe(f"a{chr(code)}b") == (f"a{chr(code)}b", False)


def test_display_safe_leaves_plain_text_alone() -> None:
    text = "echo \\x1b && printf '\\n'\n\tdone"
    assert display_safe(text) == (text, False)


def test_display_safe_never_changes_backslashes() -> None:
    # in bash this runs rm: the shown text must read the same way
    command = 'echo \\"; rm -rf /srv/data; echo \\"'
    assert display_safe(command + chr(0x200B)) == (command + marker("200B"), True)


def test_a_real_escape_and_a_typed_one_look_different() -> None:
    real = display_safe(f"printf 'a{chr(0x1B)}'")
    typed = display_safe("printf 'a\\x1b'")
    assert real == (f"printf 'a{marker('001B')}'", True)
    assert typed == ("printf 'a\\x1b'", False)


def test_a_typed_marker_cannot_pass_for_one() -> None:
    typed = marker("001B")
    assert display_safe(typed) == (f"{marker('2039')}U+001B{CLOSE}", True)
