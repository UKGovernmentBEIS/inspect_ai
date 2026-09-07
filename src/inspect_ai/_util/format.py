import pprint
import re
from logging import getLogger
from string import Formatter
from textwrap import indent
from typing import Any

from inspect_ai._util.logger import warn_once

logger = getLogger(__name__)


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
        def vformat(self, format_string: str, args: Any, kwargs: Any) -> str:
            result: list[str] = []
            for literal_text, field_name, format_spec, conversion in self.parse(
                format_string
            ):
                if literal_text:
                    result.append(literal_text)

                if field_name is None:
                    continue

                # reconstruct the placeholder exactly as it was written, so an
                # unresolvable field passes through byte-for-byte (including its
                # !conversion and :format_spec)
                original = _render_field(field_name, format_spec, conversion)

                if not self._resolvable(field_name):
                    if skip_unknown:
                        _warn_unresolved(field_name)
                        result.append(original)
                        continue
                    raise KeyError(f"Failed to format field '{field_name}'")

                try:
                    obj = super().get_field(field_name, args, kwargs)[0]
                    obj = self.convert_field(obj, conversion)
                    # a format spec may itself contain placeholders
                    spec = self.vformat(format_spec or "", args, kwargs)
                    result.append(self.format_field(obj, spec))
                except (
                    AttributeError,
                    KeyError,
                    IndexError,
                    ValueError,
                    TypeError,
                ) as e:
                    if skip_unknown:
                        _warn_unresolved(field_name)
                        result.append(original)
                    else:
                        raise KeyError(f"Failed to format field '{field_name}'") from e

            return "".join(result)

        def _resolvable(self, field_name: str) -> bool:
            """Whether field_name's root refers to a supplied param."""
            first = field_name.split(".", 1)[0].split("[", 1)[0]
            return first in params and params.get(first) is not None

    return SafeFormatter().format(template, **params)


def _render_field(
    field_name: str, format_spec: str | None, conversion: str | None
) -> str:
    """Rebuild the original `{field!conv:spec}` text of a parsed placeholder.

    `str.Formatter.parse()` reports an absent spec and an empty one identically,
    so a redundant trailing colon (`{x:}`) round-trips as `{x}`. The two format
    the same, so this is a normalization rather than a loss.
    """
    text = "{" + field_name
    if conversion:
        text += "!" + conversion
    if format_spec:
        text += ":" + format_spec
    return text + "}"


# a field name that looks like an identifier path is most likely a typo'd or
# missing param, whereas JSON-ish braces (quoted/spaced/etc.) are almost always
# literal content the author meant to keep
_VARIABLE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:[.\[][^{}]*)?$")


def _warn_unresolved(field_name: str) -> None:
    if _VARIABLE_FIELD.match(field_name):
        warn_once(
            logger,
            f"Template contains placeholder '{{{field_name}}}' which does not "
            "match any provided parameter; it will be left as-is. Use "
            "'{{' and '}}' to escape literal braces.",
        )
