from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NamedTuple, TypeVar

from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.event._sentinel import SentinelEvent

ExecutionEvent = TypeVar("ExecutionEvent", ApprovalEvent, SentinelEvent)


class _Execution(NamedTuple):
    call_id: str
    execution: str | list[ApprovalEvent | SentinelEvent]


_execution: ContextVar[_Execution | None] = ContextVar(
    "tool_call_execution", default=None
)


@contextmanager
def tool_call_execution(
    call_id: str, execution: str | list[ApprovalEvent | SentinelEvent] | None
) -> Iterator[None]:
    """Attribute the approvals and tool stage sentinel steps of the call `call_id` recorded here to an execution.

    `execution` is the `execution_id` to record them with, or, when it is not
    known yet, a list that collects them for the caller to set it on, or `None`
    for no execution. Events for other calls (an approver's or monitor's own
    tool calls) are left alone.
    """
    token = _execution.set(
        _Execution(call_id, execution) if execution is not None else None
    )
    try:
        yield
    finally:
        _execution.reset(token)


def executed(event: ExecutionEvent) -> ExecutionEvent:
    """`event`, attributed to the current execution (`tool_call_execution`)."""
    current = _execution.get()
    if current is None:
        return event
    if isinstance(event, SentinelEvent):
        if event.stage not in ("tool_call", "tool_result"):
            return event
        call_id = event.step_id
    else:
        call_id = event.call.id
    if call_id != current.call_id:
        return event
    if isinstance(current.execution, str):
        event.execution_id = current.execution
    else:
        current.execution.append(event)
    return event
