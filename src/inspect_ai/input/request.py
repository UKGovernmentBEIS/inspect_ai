from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal, cast

import anyio
from acp.schema import ElicitationSchema

from inspect_ai._util._async import coro_log_exceptions

from . import builtin
from ._config import active_input_config
from ._types import InputNotification, InputNotifier, InputRequest, InputResult

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
    metadata: dict[str, Any] | None = None,
) -> InputResult:
    """Ask the user a structured question and wait for an answer.

    Runs configured notifiers in parallel with the answer-collecting handler.
    A custom handler (if configured) runs first with a timeout; on `None` or
    timeout, dispatches to the built-in handler selection (console / panel /
    ACP, depending on runtime context).

    Args:
        message: Prompt shown to the user.
        schema: ACP `ElicitationSchema` describing the answer fields.
        metadata: Free-form passthrough for handler↔notifier correlation.

    Returns:
        `InputResult` with outcome (accepted / declined / cancelled) and
        optional `content` matching `schema`.
    """
    cfg = active_input_config()
    request = InputRequest(message=message, schema=schema)
    notification = _build_notification(request, metadata)

    result: InputResult | None = None

    async def run_handler() -> None:
        nonlocal result
        if cfg.input_handler is not None:
            with anyio.move_on_after(cfg.input_handler_timeout):
                r = await cfg.input_handler(request)
                if r is not None:
                    result = r
                    return
        result = await builtin._dispatch_builtin(request)

    async def run_notifier(n: InputNotifier) -> None:
        with anyio.move_on_after(cfg.notifier_timeout):
            await n(notification)

    async with anyio.create_task_group() as tg:
        for n in cfg.input_notifiers:
            tg.start_soon(
                coro_log_exceptions, logger, "input notifier", run_notifier, n
            )
        tg.start_soon(run_handler)

    assert result is not None
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


def _build_notification(
    request: InputRequest,
    metadata: dict[str, Any] | None,
) -> InputNotification:
    sample_id, task_name = _active_sample_context()
    return InputNotification(
        action="posted",
        request=request,
        sample_id=sample_id,
        task_name=task_name,
        metadata=metadata,
    )


def _active_sample_context() -> tuple[str, str]:
    # Local import to avoid circular dependency on log._samples
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    if active is None:
        return "", ""
    sample_id = "" if active.sample.id is None else str(active.sample.id)
    return sample_id, active.task
