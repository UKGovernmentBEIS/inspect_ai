from logging import getLogger
from typing import TYPE_CHECKING, Literal, cast

from acp.schema import ElicitationSchema

from inspect_ai.util._notify import notify

from . import builtin
from ._types import InputRequest, InputResult

if TYPE_CHECKING:
    from inspect_ai.event._input import InputField

logger = getLogger(__name__)

_FieldType = Literal["string", "integer", "number", "boolean", "array"]
_ALLOWED_FIELD_TYPES: frozenset[str] = frozenset(
    {"string", "integer", "number", "boolean", "array"}
)


async def request_input(
    *,
    message: str,
    schema: ElicitationSchema,
) -> InputResult:
    """Ask the user a structured question and wait for an answer.

    Dispatches to the built-in handler selection (ACP, Textual panel, or
    console) based on runtime context. Also fires a notification via the
    active Apprise instance (a no-op when no notifications are configured)
    so an operator who has stepped away from the terminal can be pinged.

    Args:
        message: Prompt shown to the user.
        schema: ACP `ElicitationSchema` describing the answer fields.

    Returns:
        `InputResult` with outcome (accepted / declined / cancelled) and
        optional `content` matching `schema`.
    """
    request = InputRequest(message=message, schema=schema)
    await notify(message)
    result = await builtin._dispatch_builtin(request)
    _record_input_event(request, result)
    return result


def _record_input_event(request: InputRequest, result: InputResult) -> None:
    # Deferred imports: pulling `inspect_ai.event` at module-load time triggers
    # a circular import (event -> scorer -> log -> condense -> event).
    from inspect_ai.event._input import InputEvent, InputField
    from inspect_ai.log._transcript import transcript

    fields = _fields_from_schema(request.schema, InputField)
    text = _synthesize_text(request.message, fields, result)
    transcript()._event(
        InputEvent(
            input=text,
            input_ansi=text,
            message=request.message,
            fields=fields,
            outcome=result.outcome,
            content=result.content,
        )
    )


def _fields_from_schema(
    schema: ElicitationSchema, input_field_cls: "type[InputField]"
) -> list["InputField"]:
    out: list["InputField"] = []
    for name, prop in (schema.properties or {}).items():
        raw_type = getattr(prop, "type", "")
        type_str: _FieldType = (
            cast(_FieldType, raw_type) if raw_type in _ALLOWED_FIELD_TYPES else "string"
        )
        out.append(
            input_field_cls(name=name, type=type_str, description=prop.description)
        )
    return out


def _synthesize_text(
    message: str, fields: list["InputField"], result: InputResult
) -> str:
    lines = [message]
    if result.outcome == "accepted" and result.content:
        for f in fields:
            if f.name in result.content:
                lines.append(f"  {f.name}: {result.content[f.name]}")
    elif result.outcome == "declined":
        lines.append("[declined]")
    elif result.outcome == "cancelled":
        lines.append("[cancelled]")
    return "\n".join(lines)
