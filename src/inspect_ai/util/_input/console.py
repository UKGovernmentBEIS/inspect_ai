from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import rich
from acp.schema import (
    ElicitationBooleanPropertySchema,
    ElicitationIntegerPropertySchema,
    ElicitationMultiSelectPropertySchema,
    ElicitationNumberPropertySchema,
    ElicitationSchema,
    ElicitationStringPropertySchema,
)
from rich.console import Console
from rich.prompt import Prompt

from inspect_ai.util._console import input_screen

from ._types import InputRequest, InputResult
from ._validate import (
    PropertySchema,
    multiselect_options,
    string_choice_labels,
    string_choices,
    validate_integer,
    validate_multiselect,
    validate_number,
    validate_string,
)

DECLINE_TOKEN = ":decline"


class _Declined(Exception):
    """User typed :decline at a prompt."""


_OMIT = object()  # sentinel: optional property left blank


async def console_handler(request: InputRequest) -> InputResult:
    """Built-in console handler for `request_input`.

    Walks the schema property-by-property using Rich prompts. Returns
    `accepted` with structured content on success, `declined` if the
    user types `:decline`, or `cancelled` on `KeyboardInterrupt`.
    """
    try:
        with _ask_console() as console:
            return _ask_schema(request.message, request.schema, console)
    except KeyboardInterrupt:
        return InputResult(outcome="cancelled")


@contextmanager
def _ask_console() -> Iterator[Console]:
    # Prefer the eval display's input_screen so InputEvent is recorded;
    # fall back to the bare Rich console for REPL/test contexts where
    # there's no active task screen.
    from inspect_ai._display.core.active import _active_task_screen

    if _active_task_screen.get(None) is not None:
        # request_input emits the structured InputEvent itself; opt out of
        # input_screen's text-dump emission to avoid double-logging.
        with input_screen(record_event=False) as console:
            yield console
    else:
        yield rich.get_console()


def _ask_schema(
    message: str, schema: ElicitationSchema, console: Console
) -> InputResult:
    if schema.title:
        console.print(f"[bold]{schema.title}[/bold]")
    console.print(message)
    if schema.description:
        console.print(f"[dim]{schema.description}[/dim]")
    console.print(f"[dim](Type {DECLINE_TOKEN} at any prompt to decline.)[/dim]")

    required = set(schema.required or [])
    content: dict[str, Any] = {}

    try:
        for name, prop in (schema.properties or {}).items():
            value = _ask_property(name, prop, name in required, console)
            if value is not _OMIT:
                content[name] = value
    except _Declined:
        return InputResult(outcome="declined")

    return InputResult(outcome="accepted", content=content)


def _ask_property(
    name: str, prop: PropertySchema, required: bool, console: Console
) -> Any:
    label = prop.title or name
    if prop.description:
        console.print(f"[dim]{prop.description}[/dim]")

    if isinstance(prop, ElicitationStringPropertySchema):
        return _ask_string(label, prop, required, console)
    if isinstance(prop, ElicitationIntegerPropertySchema):
        return _ask_integer(label, prop, required, console)
    if isinstance(prop, ElicitationNumberPropertySchema):
        return _ask_number(label, prop, required, console)
    if isinstance(prop, ElicitationBooleanPropertySchema):
        return _ask_boolean(label, prop, required, console)
    if isinstance(prop, ElicitationMultiSelectPropertySchema):
        return _ask_multiselect(label, prop, required, console)
    raise ValueError(f"Unsupported property type: {type(prop).__name__}")


def _check_decline(value: str) -> None:
    if value.strip() == DECLINE_TOKEN:
        raise _Declined()


def _ask_string(
    label: str,
    prop: ElicitationStringPropertySchema,
    required: bool,
    console: Console,
) -> Any:
    if prop.format:
        console.print(f"[dim](format: {prop.format})[/dim]")

    # Print options for bounded-choice strings; we deliberately do NOT pass
    # `choices=` to Prompt.ask because Rich would reject `:decline` before we
    # get a chance to handle it.
    labels = string_choice_labels(prop)
    if labels is not None:
        if prop.one_of is not None:
            for const, title in labels:
                console.print(f"  [cyan]{const}[/cyan]: {title}")
        else:
            console.print(
                f"[dim]options: {', '.join(string_choices(prop) or [])}[/dim]"
            )

    while True:
        value = Prompt.ask(
            label,
            console=console,
            default=prop.default if prop.default is not None else "",
            show_default=prop.default is not None,
        )
        _check_decline(value)

        if not value:
            if required:
                console.print(f"[red]{label} is required.[/red]")
                continue
            return _OMIT

        accepted, error = validate_string(prop, value)
        if error is not None:
            console.print(f"[red]{error}[/red]")
            continue
        return accepted


def _ask_integer(
    label: str,
    prop: ElicitationIntegerPropertySchema,
    required: bool,
    console: Console,
) -> Any:
    return _ask_numeric(label, prop, required, console)


def _ask_number(
    label: str,
    prop: ElicitationNumberPropertySchema,
    required: bool,
    console: Console,
) -> Any:
    return _ask_numeric(label, prop, required, console)


def _ask_numeric(
    label: str,
    prop: ElicitationIntegerPropertySchema | ElicitationNumberPropertySchema,
    required: bool,
    console: Console,
) -> Any:
    # Ask as a string so we can detect blank (optional → omit) and `:decline`,
    # then dispatch to the type-appropriate validator.
    minimum = prop.minimum
    maximum = prop.maximum
    if minimum is not None or maximum is not None:
        bounds = []
        if minimum is not None:
            bounds.append(f">= {minimum}")
        if maximum is not None:
            bounds.append(f"<= {maximum}")
        console.print(f"[dim]({', '.join(bounds)})[/dim]")

    while True:
        raw = Prompt.ask(
            label,
            console=console,
            default="" if prop.default is None else str(prop.default),
            show_default=prop.default is not None,
        )
        _check_decline(raw)

        if not raw:
            if required:
                console.print(f"[red]{label} is required.[/red]")
                continue
            return _OMIT

        result: Any
        if isinstance(prop, ElicitationIntegerPropertySchema):
            result, error = validate_integer(prop, raw)
        else:
            result, error = validate_number(prop, raw)
        if error is not None:
            console.print(f"[red]{error}[/red]")
            continue
        return result


def _ask_boolean(
    label: str,
    prop: ElicitationBooleanPropertySchema,
    required: bool,
    console: Console,
) -> Any:
    # Drive boolean prompts through Prompt.ask (not Confirm.ask) so we can
    # support `:decline` and blank-means-omit on optional booleans.
    default_str = ""
    if prop.default is not None:
        default_str = "y" if prop.default else "n"

    while True:
        raw = Prompt.ask(
            f"{label} [y/n]",
            console=console,
            default=default_str,
            show_default=bool(default_str),
        )
        _check_decline(raw)

        s = raw.strip().lower()
        if not s:
            if required:
                console.print(f"[red]{label} is required.[/red]")
                continue
            return _OMIT
        if s in ("y", "yes", "true"):
            return True
        if s in ("n", "no", "false"):
            return False
        console.print("[red]Please answer y or n.[/red]")


def _ask_multiselect(
    label: str,
    prop: ElicitationMultiSelectPropertySchema,
    required: bool,
    console: Console,
) -> Any:
    options = multiselect_options(prop)

    for i, (const, title) in enumerate(options, start=1):
        if const == title:
            console.print(f"  [cyan]{i}[/cyan]: {title}")
        else:
            console.print(f"  [cyan]{i}[/cyan]: {title} ({const})")

    min_items = prop.min_items
    max_items = prop.max_items
    if min_items is not None or max_items is not None:
        bounds = []
        if min_items is not None:
            bounds.append(f"min {min_items}")
        if max_items is not None:
            bounds.append(f"max {max_items}")
        console.print(f"[dim]({', '.join(bounds)})[/dim]")

    default_text = ""
    if prop.default:
        # Map default values back to indices for display
        idx_by_const = {const: i for i, (const, _) in enumerate(options, start=1)}
        default_text = ",".join(
            str(idx_by_const[v]) for v in prop.default if v in idx_by_const
        )

    while True:
        raw = Prompt.ask(
            f"{label} (comma-separated indices)",
            console=console,
            default=default_text,
            show_default=bool(default_text),
        )
        _check_decline(raw)

        if not raw:
            # An empty selection is schema-valid when min_items is unset or 0,
            # even for a "required" array — the array itself was provided.
            min_required = min_items or 0
            if min_required == 0:
                return [] if required else _OMIT
            console.print(f"[red]Select at least {min_required}.[/red]")
            continue

        parts = [p.strip() for p in raw.split(",") if p.strip()]
        try:
            indices = [int(p) for p in parts]
        except ValueError:
            console.print("[red]Enter comma-separated index numbers (e.g. 1,3).[/red]")
            continue

        if any(i < 1 or i > len(options) for i in indices):
            console.print(f"[red]Indices must be between 1 and {len(options)}.[/red]")
            continue

        # de-dupe while preserving order
        seen: set[int] = set()
        unique_indices: list[int] = []
        for i in indices:
            if i not in seen:
                seen.add(i)
                unique_indices.append(i)

        values = [options[i - 1][0] for i in unique_indices]
        accepted, error = validate_multiselect(prop, values)
        if error is not None:
            console.print(f"[red]{error}[/red]")
            continue
        return accepted
