import asyncio
import uuid
from asyncio import Future
from contextvars import ContextVar
from typing import Callable, Literal, NamedTuple, cast

from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from .._approval import Approval, ApprovalDecision


class ApprovalRequest(NamedTuple):
    message: str
    call: ToolCall
    view: ToolCallView
    state: TaskState | None
    choices: list[ApprovalDecision]


class PendingApprovalRequest(NamedTuple):
    request: ApprovalRequest
    task: str
    model: str
    id: int | str
    epoch: int


class HumanApprovalManager:
    def __init__(self) -> None:
        self._approval_requests: dict[
            str, tuple[PendingApprovalRequest, Future[Approval]]
        ] = {}
        self._change_callbacks: list[Callable[[Literal["add", "remove"]], None]] = []

    def request_approval(self, request: ApprovalRequest) -> str:
        from inspect_ai.log._samples import sample_active

        id = str(uuid.uuid4())
        future = cast(Future[Approval], asyncio.get_event_loop().create_future())
        sample = sample_active()
        assert sample
        assert sample.sample.id
        pending = PendingApprovalRequest(
            request=request,
            task=sample.task,
            model=sample.model,
            id=sample.sample.id,
            epoch=sample.epoch,
        )
        self._approval_requests[id] = (pending, future)
        self._notify_change("add")
        return id

    def withdraw_request(self, id: str) -> None:
        del self._approval_requests[id]
        self._notify_change("remove")

    async def wait_for_approval(self, id: str) -> Approval:
        _, future = self._approval_requests[id]
        return await future

    def on_change(
        self, callback: Callable[[Literal["add", "remove"]], None]
    ) -> Callable[[], None]:
        self._change_callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._change_callbacks:
                self._change_callbacks.remove(callback)

        return unsubscribe

    def approval_requests(self) -> list[tuple[str, PendingApprovalRequest]]:
        return [(aid, data) for aid, (data, _) in self._approval_requests.items()]

    def complete_approval(self, id: str, result: Approval) -> None:
        if id in self._approval_requests:
            _, future = self._approval_requests[id]
            if not future.done():
                future.set_result(result)
            del self._approval_requests[id]
            self._notify_change("remove")

    def fail_approval(self, id: str, error: Exception) -> None:
        if id in self._approval_requests:
            _, future = self._approval_requests[id]
            if not future.done():
                future.set_exception(error)
            del self._approval_requests[id]
            self._notify_change("remove")

    def _notify_change(self, action: Literal["add", "remove"]) -> None:
        for callback in self._change_callbacks:
            callback(action)


def human_approval_manager() -> HumanApprovalManager:
    return _human_approval_manager.get()


def init_human_approval_manager() -> None:
    _human_approval_manager.set(HumanApprovalManager())


_human_approval_manager: ContextVar[HumanApprovalManager] = ContextVar(
    "_human_approval_manager"
)
