import pprint
import re
import unicodedata
from keyword import iskeyword
from string import Formatter
from textwrap import indent
from typing import Any, NamedTuple


def format_function_call(
    func_name: str,
    args_dict: dict[str, Any],
    indent_spaces: int = 4,
    width: int = 80,
    literal_strings: bool = False,
) -> str:
    r"""Format a function call for display.

    Args:
        func_name: The function's name.
        args_dict: The call's arguments.
        indent_spaces: Indentation of arguments when the call spans lines.
        width: Line width to wrap the arguments at.
        literal_strings: Show strings as Python literals, with quotes,
            newlines and invisible characters escaped, so a string cannot
            read as other arguments or as another string. Argument names
            other than plain ASCII identifiers are then shown in an
            unpacked dictionary with non-ASCII characters escaped
            (`**{'a b': 1, 'caf\xe9': 2}`), so a name cannot read as
            other arguments or as another name either.
    """
    formatted_args = []
    unnamed: list[str] = []
    for key, value in args_dict.items():
        formatted_value = format_value(value, width, literal_strings)
        if literal_strings:
            formatted_value = _escape_invisible(formatted_value)
            if not _is_keyword_argument(key):
                unnamed.append(f"{ascii(key)}: {formatted_value}")
                continue
        formatted_args.append(f"{key}={formatted_value}")
    if unnamed:
        formatted_args.append("**{" + ", ".join(unnamed) + "}")

    args_str = ", ".join(formatted_args)

    if len(args_str) <= width - 1 - len(func_name) - 2:  # 2 for parentheses
        return f"{func_name}({args_str})"
    else:
        indented_args = indent(",\n".join(formatted_args), " " * indent_spaces)
        return f"{func_name}(\n{indented_args}\n)"


def _is_keyword_argument(name: object) -> bool:
    # only plain ASCII names: other identifiers can read as another name
    # (full-width letters, invisible combining marks)
    return (
        isinstance(name, str)
        and name.isascii()
        and name.isidentifier()
        and not iskeyword(name)
    )


# Unicode default-ignorable code points (DerivedCoreProperties.txt), which
# render as nothing; this includes the Hangul fillers, which render blank
_INVISIBLE_RANGES = [
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
]
_INVISIBLE = re.compile(
    "[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _INVISIBLE_RANGES) + "]"
)


def _escape_invisible(literal: str) -> str:
    """A Python literal with its invisible characters written as escapes.

    `repr()` escapes characters that are not printable, but leaves some that
    render as nothing (a combining grapheme joiner, variation selectors,
    Hangul fillers). In a literal these can only occur inside a string, where
    the escape denotes the same character.
    """
    return _INVISIBLE.sub(lambda m: ascii(m.group(0))[1:-1], literal)


def format_value(value: object, width: int, literal_strings: bool = False) -> str:
    if isinstance(value, str) and not literal_strings:
        return f"'{value}'"
    elif isinstance(value, str | list | tuple | dict):
        return pprint.pformat(value, width=width)
    return str(value)


def safe_code_fence(content: str) -> str:
    """Return a backtick fence longer than any backtick run in ``content``.

    CommonMark / GFM rule: a fenced code block opened with N
    backticks closes at the next line whose fence has at least N
    backticks. Pick ``max_run + 1`` so the close fence we emit
    can't be matched by anything embedded in the content.

    Minimum length 3 — keeps standard plaintext (no backticks at
    all) wrapped in the familiar ``` fence.

    Control and format characters other than newline and tab do not end a
    run: a renderer that removes them (as the ACP TUI does) would join the
    backticks around them into one longer run.
    """
    max_run = 0
    cur_run = 0
    for ch in content:
        if ch == "`":
            cur_run += 1
            if cur_run > max_run:
                max_run = cur_run
        elif ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf"):
            cur_run = 0
    return "`" * max(3, max_run + 1)


def markdown_escaped(text: str) -> str:
    """Text with markdown punctuation escaped, so it adds no structure."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~&])", r"\\\1", text)


class DisplaySafe(NamedTuple):
    """Text made safe to show a person, and whether anything was replaced."""

    text: str
    escaped: bool


# code points shown as escapes: C0 controls other than tab and newline, DEL,
# C1 controls (8-bit CSI among them), zero-width characters and the word
# joiner, bidi embeddings and overrides, bidi isolates, the zero-width
# no-break space, and the tag block; and the marker's own opening character,
# so a marker cannot be typed
_UNSAFE_RANGES = [
    (0x00, 0x08),
    (0x0B, 0x1F),
    (0x7F, 0x9F),
    (0x200B, 0x200D),
    (0x2039, 0x2039),
    (0x2060, 0x2060),
    (0x202A, 0x202E),
    (0x2066, 0x2069),
    (0xFEFF, 0xFEFF),
    (0xE0000, 0xE007F),
]
_UNSAFE = re.compile(
    "["
    + "".join(f"{re.escape(chr(a))}-{re.escape(chr(b))}" for a, b in _UNSAFE_RANGES)
    + "]"
)

# single angle quotation marks around the code point, e.g. ESC as U+001B
MARKER_OPEN = chr(0x2039)
MARKER_CLOSE = chr(0x203A)


def display_safe(text: str) -> DisplaySafe:
    """Text with every control and invisible character shown as a marker.

    Text from a model shown to a person (a tool call's arguments, an
    assistant message) can carry characters that act rather than show: a
    terminal escape sequence moves the cursor and overwrites what is on
    screen, a bidi override reorders what follows, and a zero-width or tag
    character hides text. As OpenBSD's `vis(3)` does, each is shown visibly
    instead, never passed through or silently removed, so the person sees it
    was there: the code point between single angle quotation marks, ESC as
    `U+001B` in them, a tag character as `U+E0041`. The classes are the C0
    controls other than newline and tab, DEL, the C1 controls, zero-width
    characters and the word joiner, bidi embeddings, overrides and isolates,
    the zero-width no-break space, and the tag block.

    The marker is not a backslash escape, so backslashes are never changed
    and code reads exactly as written except at a marker. The marker's
    opening character is itself shown as a marker wherever it appears in the
    text, so typed text cannot pass for one.

    Args:
        text: The text to show.

    Returns:
        The text to show, and whether anything in it was replaced by a marker.
    """
    shown, count = _UNSAFE.subn(_marker, text)
    return DisplaySafe(shown, count > 0)


def _marker(match: re.Match[str]) -> str:
    return f"{MARKER_OPEN}U+{ord(match.group()):04X}{MARKER_CLOSE}"


def format_progress_time(time: float, pad_hours: bool = True) -> str:
    # Truncate sub-second elapsed time before splitting into H:MM:SS. The
    # ".0f" format specs round, so a fractional component >= x.5 (e.g. 59.9s)
    # would otherwise render an impossible ":60" in the seconds (or minutes)
    # field of a live clock.
    total_seconds = int(time)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    hours_fmt = f"{hours:2d}" if pad_hours else f"{hours:d}"
    return f"{hours_fmt}:{minutes:02d}:{seconds:02d}"


def format_template(
    template: str,
    params: dict[str, Any],
    skip_unknown: bool = True,
) -> str:
    """Format a template string, optionally preserving unknown placeholders.

    Args:
        template: A string containing {placeholders} to be formatted
        params: Dictionary of parameters to substitute into the template
        skip_unknown: If True, preserve unknown placeholders; if False, raise KeyError

    Returns:
        The formatted string with parameters substituted

    Examples:
        >>> format_template("Hello {name}!", {"name": "World"})
        'Hello World!'
        >>> format_template("Hello {name}!", {}, skip_unknown=True)
        'Hello {name}!'
    """

    class SafeFormatter(Formatter):
        def get_field(self, field_name: str, args: Any, kwargs: Any) -> Any:
            try:
                # Handle array indexing and nested attributes
                first, rest = (
                    field_name.split(".", 1)
                    if "." in field_name
                    else (field_name, None)
                )
                first = first.split("[")[0]  # Remove any array indexing for the check

                if first not in params and skip_unknown:
                    return "{" + field_name + "}", field_name

                obj = params.get(first)
                if obj is None and skip_unknown:
                    return "{" + field_name + "}", field_name

                return super().get_field(field_name, args, kwargs)
            except (AttributeError, KeyError, IndexError) as e:
                if skip_unknown:
                    return "{" + field_name + "}", field_name
                raise KeyError(f"Failed to format field '{field_name}'") from e

        def format_field(self, value: Any, format_spec: str) -> Any:
            try:
                return super().format_field(value, format_spec)
            except (ValueError, TypeError):
                if skip_unknown:
                    return "{" + str(value) + ":" + format_spec + "}"
                raise

    return SafeFormatter().format(template, **params)
