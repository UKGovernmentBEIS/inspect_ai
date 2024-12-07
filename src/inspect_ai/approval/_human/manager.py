import asyncio
import uuid
from asyncio import Future
from contextvars import ContextVar
from typing import Callable, NamedTuple, cast

from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from .._approval import Approval, ApprovalDecision


class ApprovalRequest(NamedTuple):
    message: str
    call: ToolCall
    view: ToolCallView
    state: TaskState | None
    choices: list[ApprovalDecision]


class HumanApprovalManager:
    def __init__(self) -> None:
        self._approval_requests: dict[
            str, tuple[ApprovalRequest, Future[Approval]]
        ] = {}
        self._change_callbacks: list[Callable[[], None]] = []

    async def approve(self, request: ApprovalRequest) -> Approval:
        id = str(uuid.uuid4())
        future = cast(Future[Approval], asyncio.get_event_loop().create_future())
        self._approval_requests[id] = (request, future)
        self._notify_change()
        return await future

    def on_change(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._change_callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._change_callbacks:
                self._change_callbacks.remove(callback)

        return unsubscribe

    def approval_requests(self) -> list[tuple[str, ApprovalRequest]]:
        return [(aid, data) for aid, (data, _) in self._approval_requests.items()]

    def complete_approval(self, id: str, result: Approval) -> None:
        if id in self._approval_requests:
            _, future = self._approval_requests[id]
            if not future.done():
                future.set_result(result)
            del self._approval_requests[id]
            self._notify_change()

    def fail_approval(self, id: str, error: Exception) -> None:
        if id in self._approval_requests:
            _, future = self._approval_requests[id]
            if not future.done():
                future.set_exception(error)
            del self._approval_requests[id]
            self._notify_change()

    def _notify_change(self) -> None:
        for callback in self._change_callbacks:
            callback()


def human_approval_manager() -> HumanApprovalManager:
    return _human_approval_manager.get()


def init_human_approval_manager() -> None:
    _human_approval_manager.set(HumanApprovalManager())


_human_approval_manager: ContextVar[HumanApprovalManager] = ContextVar(
    "_human_approval_manager"
)
