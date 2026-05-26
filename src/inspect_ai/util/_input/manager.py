import uuid
from contextvars import ContextVar
from typing import Callable, Literal, NamedTuple

from inspect_ai._util.future import Future

from ._types import InputRequest, InputResult


class PendingQuestionRequest(NamedTuple):
    request: InputRequest
    task: str
    id: int | str
    epoch: int


class HumanQuestionManager:
    """In-process queue of pending `ask_user` interactions.

    Mirrors `HumanApprovalManager` (`approval/_human/manager.py:28-104`):
    the panel subscribes to `on_change` and the entry-point coroutine
    awaits the per-request `Future[InputResult]`.
    """

    def __init__(self) -> None:
        self._question_requests: dict[
            str, tuple[PendingQuestionRequest, Future[InputResult]]
        ] = {}
        self._change_callbacks: list[Callable[[Literal["add", "remove"]], None]] = []

    def request_question(self, request: InputRequest) -> str:
        from inspect_ai.log._samples import sample_active

        id = str(uuid.uuid4())
        sample = sample_active()
        if sample is not None:
            sample_id: int | str = "" if sample.sample.id is None else sample.sample.id
            task = sample.task
            epoch = sample.epoch
        else:
            sample_id = ""
            task = ""
            epoch = 0
        pending = PendingQuestionRequest(
            request=request, task=task, id=sample_id, epoch=epoch
        )
        self._question_requests[id] = (pending, Future[InputResult]())
        self._notify_change("add")
        return id

    def withdraw_request(self, id: str) -> None:
        if id in self._question_requests:
            del self._question_requests[id]
            self._notify_change("remove")

    async def wait_for_question(self, id: str) -> InputResult:
        _, future = self._question_requests[id]
        return await future.result()

    def on_change(
        self, callback: Callable[[Literal["add", "remove"]], None]
    ) -> Callable[[], None]:
        self._change_callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._change_callbacks:
                self._change_callbacks.remove(callback)

        return unsubscribe

    def question_requests(self) -> list[tuple[str, PendingQuestionRequest]]:
        return [(qid, data) for qid, (data, _) in self._question_requests.items()]

    def complete_question(self, id: str, result: InputResult) -> None:
        if id in self._question_requests:
            _, future = self._question_requests[id]
            future.set_result(result)
            del self._question_requests[id]
            self._notify_change("remove")

    def fail_question(self, id: str, error: Exception) -> None:
        if id in self._question_requests:
            _, future = self._question_requests[id]
            future.set_exception(error)
            del self._question_requests[id]
            self._notify_change("remove")

    def _notify_change(self, action: Literal["add", "remove"]) -> None:
        for callback in self._change_callbacks:
            callback(action)


def human_question_manager() -> HumanQuestionManager:
    return _human_question_manager.get()


def init_human_question_manager() -> None:
    _human_question_manager.set(HumanQuestionManager())


_human_question_manager: ContextVar[HumanQuestionManager] = ContextVar(
    "_human_question_manager"
)
