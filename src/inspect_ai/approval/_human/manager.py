import uuid
from contextvars import ContextVar
from typing import Callable, Literal, NamedTuple

import anyio

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


class ApprovalState:
    def __init__(self) -> None:
        self.result: Approval | None = None
        self.error: Exception | None = None
        self.event = anyio.Event()


class HumanApprovalManager:
    def __init__(self) -> None:
        self._approval_requests: dict[
            str, tuple[PendingApprovalRequest, ApprovalState]
        ] = {}
        self._change_callbacks: list[Callable[[Literal["add", "remove"]], None]] = []

    def request_approval(self, request: ApprovalRequest) -> str:
        from inspect_ai.log._samples import sample_active

        id = str(uuid.uuid4())
        sample = sample_active()
        assert sample
        assert sample.sample.id is not None
        pending = PendingApprovalRequest(
            request=request,
            task=sample.task,
            model=sample.model,
            id=sample.sample.id,
            epoch=sample.epoch,
        )
        self._approval_requests[id] = (pending, ApprovalState())
        self._notify_change("add")
        return id

    def withdraw_request(self, id: str) -> None:
        del self._approval_requests[id]
        self._notify_change("remove")

    async def wait_for_approval(self, id: str) -> Approval:
        _, state = self._approval_requests[id]
        await state.event.wait()
        if state.result is not None:
            return state.result
        elif state.error is not None:
            raise state.error
        else:
            raise RuntimeError("Approval ended without result or error.")

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
            _, state = self._approval_requests[id]
            state.result = result
            state.event.set()
            del self._approval_requests[id]
            self._notify_change("remove")

    def fail_approval(self, id: str, error: Exception) -> None:
        if id in self._approval_requests:
            _, state = self._approval_requests[id]
            state.error = error
            state.event.set()
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
