import pprint
import re
from string import Formatter
from textwrap import indent
from typing import Any, NamedTuple


def format_function_call(
    func_name: str, args_dict: dict[str, Any], indent_spaces: int = 4, width: int = 80
) -> str:
    formatted_args = []
    for key, value in args_dict.items():
        formatted_value = format_value(value, width)
        formatted_args.append(f"{key}={formatted_value}")

    args_str = ", ".join(formatted_args)

    if len(args_str) <= width - 1 - len(func_name) - 2:  # 2 for parentheses
        return f"{func_name}({args_str})"
    else:
        indented_args = indent(",\n".join(formatted_args), " " * indent_spaces)
        return f"{func_name}(\n{indented_args}\n)"


def format_value(value: object, width: int) -> str:
    if isinstance(value, str):
        return f"'{value}'"
    elif isinstance(value, list | tuple | dict):
        return pprint.pformat(value, width=width)
    return str(value)


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
