from logging import getLogger
from typing import Any

import anyio
from acp.schema import ElicitationSchema

from inspect_ai._util._async import coro_log_exceptions

from . import builtin
from ._config import active_input_config
from ._types import InputNotification, InputNotifier, InputResult

logger = getLogger(__name__)


async def request_input(
    message: str,
    schema: ElicitationSchema,
    *,
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
    notification = _build_notification(message, schema, metadata)

    result: InputResult | None = None

    async def run_handler() -> None:
        nonlocal result
        if cfg.input_handler is not None:
            with anyio.move_on_after(cfg.input_handler_timeout):
                r = await cfg.input_handler(message, schema)
                if r is not None:
                    result = r
                    return
        result = await builtin._dispatch_builtin(message, schema)

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
    return result


def _build_notification(
    message: str,
    schema: ElicitationSchema,
    metadata: dict[str, Any] | None,
) -> InputNotification:
    sample_id, task_name = _active_sample_context()
    return InputNotification(
        event="posted",
        message=message,
        schema=schema,
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
