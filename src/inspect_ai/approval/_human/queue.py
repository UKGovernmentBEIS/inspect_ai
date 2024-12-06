import asyncio
import uuid
from asyncio import Future
from contextvars import ContextVar
from typing import NamedTuple, cast

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
        self._pending_approvals: dict[
            str, tuple[ApprovalRequest, Future[Approval]]
        ] = {}

    async def approve(self, request: ApprovalRequest) -> Approval:
        id = str(uuid.uuid4())
        future = cast(Future[Approval], asyncio.get_event_loop().create_future())
        self._pending_approvals[id] = (request, future)
        return await future

    def pending_approvals(self) -> list[tuple[str, ApprovalRequest]]:
        return [(aid, data) for aid, (data, _) in self._pending_approvals.items()]

    def complete_approval(self, id: str, result: Approval) -> None:
        if id in self._pending_approvals:
            _, future = self._pending_approvals[id]
            if not future.done():
                future.set_result(result)
            del self._pending_approvals[id]

    def fail_approval(self, id: str, error: Exception) -> None:
        if id in self._pending_approvals:
            _, future = self._pending_approvals[id]
            if not future.done():
                future.set_exception(error)
            del self._pending_approvals[id]


def human_approval_manager() -> HumanApprovalManager:
    return _human_approval_manager.get()


def init_human_approval_manager() -> None:
    _human_approval_manager.set(HumanApprovalManager())


_human_approval_manager: ContextVar[HumanApprovalManager] = ContextVar(
    "_human_approval_manager"
)
