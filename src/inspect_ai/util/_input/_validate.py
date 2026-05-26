"""Shared per-property validation predicates for `ElicitationSchema`.

Both the console handler (`console.py`) and the Textual panel widget
(`_util/textual/form.py`) parse raw user input against the same schema
constraints. The helpers here keep that logic in one place: each takes
a property schema plus already-parsed-or-raw input and returns either
the accepted value or a human-readable error message.
"""

import re
from typing import Any, Union

from acp.schema import (
    ElicitationBooleanPropertySchema,
    ElicitationIntegerPropertySchema,
    ElicitationMultiSelectPropertySchema,
    ElicitationNumberPropertySchema,
    ElicitationStringPropertySchema,
    TitledMultiSelectItems,
    UntitledMultiSelectItems,
)

PropertySchema = Union[
    ElicitationStringPropertySchema,
    ElicitationIntegerPropertySchema,
    ElicitationNumberPropertySchema,
    ElicitationBooleanPropertySchema,
    ElicitationMultiSelectPropertySchema,
]


def validate_string(
    prop: ElicitationStringPropertySchema, value: str
) -> tuple[str | None, str | None]:
    """Validate a string property value.

    Returns `(accepted_value, None)` on success or `(None, error)` on failure.
    """
    choices = _string_choices(prop)
    if choices is not None and value not in choices:
        return None, f"Please choose one of: {', '.join(choices)}."
    if prop.min_length is not None and len(value) < prop.min_length:
        return None, f"Must be at least {prop.min_length} characters."
    if prop.max_length is not None and len(value) > prop.max_length:
        return None, f"Must be at most {prop.max_length} characters."
    if prop.pattern is not None and not re.fullmatch(prop.pattern, value):
        return None, f"Must match pattern: {prop.pattern}"
    return value, None


def validate_integer(
    prop: ElicitationIntegerPropertySchema, raw: str
) -> tuple[int | None, str | None]:
    try:
        value = int(raw)
    except ValueError:
        return None, "Please enter a valid integer."
    return _check_numeric_range(prop.minimum, prop.maximum, value)


def validate_number(
    prop: ElicitationNumberPropertySchema, raw: str
) -> tuple[float | None, str | None]:
    try:
        value = float(raw)
    except ValueError:
        return None, "Please enter a valid number."
    return _check_numeric_range(prop.minimum, prop.maximum, value)


def validate_multiselect(
    prop: ElicitationMultiSelectPropertySchema, values: list[str]
) -> tuple[list[str] | None, str | None]:
    """Validate a multi-select array against its bounds and allowed consts."""
    allowed = {c for c, _ in multiselect_options(prop)}
    for v in values:
        if v not in allowed:
            return None, f"{v!r} is not a valid choice."

    seen: set[str] = set()
    unique: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            unique.append(v)

    if prop.min_items is not None and len(unique) < prop.min_items:
        return None, f"Select at least {prop.min_items}."
    if prop.max_items is not None and len(unique) > prop.max_items:
        return None, f"Select at most {prop.max_items}."
    return unique, None


def multiselect_options(
    prop: ElicitationMultiSelectPropertySchema,
) -> list[tuple[str, str]]:
    """Resolve `(const, display_label)` pairs from a multi-select property."""
    if isinstance(prop.items, TitledMultiSelectItems):
        return [(opt.const, opt.title) for opt in prop.items.any_of]
    if isinstance(prop.items, UntitledMultiSelectItems):
        return [(v, v) for v in prop.items.enum]
    raise ValueError(f"Unsupported multi-select items: {type(prop.items).__name__}")


def string_choices(prop: ElicitationStringPropertySchema) -> list[str] | None:
    """Return the closed-set of allowed strings, or `None` if free-form."""
    return _string_choices(prop)


def string_choice_labels(
    prop: ElicitationStringPropertySchema,
) -> list[tuple[str, str]] | None:
    """Return `(const, label)` pairs when the property has bounded choices.

    For `one_of`, label is the option title. For `enum`, label equals the
    constant value. Returns `None` for free-form strings.
    """
    if prop.one_of is not None:
        return [(opt.const, opt.title) for opt in prop.one_of]
    if prop.enum is not None:
        return [(v, v) for v in prop.enum]
    return None


def _string_choices(prop: ElicitationStringPropertySchema) -> list[str] | None:
    if prop.one_of is not None:
        return [opt.const for opt in prop.one_of]
    if prop.enum is not None:
        return list(prop.enum)
    return None


def _check_numeric_range(
    minimum: float | int | None,
    maximum: float | int | None,
    value: Any,
) -> tuple[Any, str | None]:
    if minimum is not None and value < minimum:
        return None, f"Must be >= {minimum}."
    if maximum is not None and value > maximum:
        return None, f"Must be <= {maximum}."
    return value, None
