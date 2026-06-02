import contextlib
from contextlib import AbstractAsyncContextManager
from contextvars import ContextVar
from datetime import datetime, timezone
from logging import getLogger
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Iterator,
    Literal,
)

if TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

    from inspect_ai.agent._acp.transport import AcpTransport
    from inspect_ai.agent._channel import ExecutionObserver
    from inspect_ai.hooks._hooks import SampleEvent
    from inspect_ai.log._log import EvalRetryError
    from inspect_ai.model._model_call import ModelCall, ModelCallFilter

import anyio
from anyio.abc import TaskGroup
from shortuuid import uuid

from inspect_ai.dataset._dataset import Sample
from inspect_ai.util._checkpoint.checkpointer import Checkpointer, ResumeCheckpoint
from inspect_ai.util._checkpoint.checkpointer_factory import create_checkpointer
from inspect_ai.util._checkpoint.config import ResolvedCheckpointConfig
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._sandbox import SandboxConnection
from inspect_ai.util._sandbox.context import sandbox_connections

from ..event._model import ModelEvent
from ._transcript import Transcript

logger = getLogger(__name__)


class ActiveSample:
    def __init__(
        self,
        *,
        task: str,
        log_location: str,
        model: str,
        sample: Sample,
        epoch: int,
        message_limit: int | None,
        token_limit: int | None,
        cost_limit: float | None,
        time_limit: int | None,
        working_limit: int | None,
        fails_on_error: bool,
        transcript: Transcript,
        sandboxes: dict[str, SandboxConnection],
        checkpointer: AbstractAsyncContextManager[Checkpointer],
        eval_id: str,
        eval_set_id: str | None = None,
        run_id: str | None = None,
        agent_name: str | None = None,
        error_retries: "list[EvalRetryError] | None" = None,
    ) -> None:
        self.id = uuid()
        self.started: float | None = None
        self.tg: TaskGroup | None = None
        self.completed: float | None = None
        self.task = task
        self.log_location = log_location
        self.model = model
        self.sample = sample
        self.epoch = epoch
        self.message_limit = message_limit
        self.token_limit = token_limit
        self.cost_limit = cost_limit
        self.time_limit = time_limit
        self.working_limit = working_limit
        self.fails_on_error = fails_on_error
        self.total_messages = 0
        self.total_tokens = 0
        self.total_cost: float | None = None
        self.transcript = transcript
        self.sandboxes = sandboxes
        self.checkpointer = checkpointer
        self.eval_set_id = eval_set_id
        self.run_id = run_id
        self.eval_id = eval_id
        self.agent_name = agent_name
        # Prior failed attempts for this sample (genuine errors only):
        # sample-level `retry_on_error` plus task-level retries seeded via the
        # sample source. Empty on the first attempt. The control channel
        # surfaces these as the running sample's error history.
        self.error_retries: list[EvalRetryError] = error_retries or []
        self._interrupt_action: Literal["score", "error"] | None = None
        self._limit_exceeded_error: LimitExceededError | None = None
        self.event_send: MemoryObjectSendStream[SampleEvent] | None = None
        self.event_receive: MemoryObjectReceiveStream[SampleEvent] | None = None
        self.event_done: anyio.Event | None = None
        # Live ACP session for this sample, if any. Set by
        # `LiveAcpTransport.__aenter__` on entry; cleared at `__aexit__`.
        # The Inspect TUI reads this to decide whether to render the
        # Interrupt button and to dispatch session/cancel + session/prompt.
        self.acp_transport: "AcpTransport | None" = None
        # Pending human-in-the-loop interaction counts. Incremented by
        # the ACP routing shims (approval/_human/acp.py, input/acp.py)
        # on entry to their park-on-attach wait, decremented in
        # `finally`. Stored as counters (not a single Literal slot)
        # because `parallel=True` tool calls run concurrently within
        # one sample (see `_call_tools.py`); two approvals can be
        # in-flight at once, and a single-slot save/restore would clear
        # the picker indicator while the second wait is still pending.
        # The `pending_interaction` property below derives the
        # picker-visible state from these counters.
        self._pending_approvals: int = 0
        self._pending_questions: int = 0
        # In-flight tool/model tracking observer for this sample.
        # Defaults to a no-op singleton; an intervention producer (the
        # ACP transport today, future supervisors) installs itself here
        # to record `InterruptEvent` cross-references when it cancels.
        # The model/tool layers wrap each top-level tool execution and
        # each model generation in the observer's `track_*` context
        # manager, so the producer always has the necessary provenance
        # available at cancel time.
        from inspect_ai.agent._channel import null_execution_observer

        self.execution_observer: "ExecutionObserver" = null_execution_observer()
        # Lifecycle callbacks owned by whoever bound to this sample
        # (in practice, the live ACP session). Kept here rather than
        # in the ACP layer so the eval primitive doesn't have to
        # import or call into ACP — it just fires the registered hook
        # if present. `on_complete` runs after scoring + logging
        # finish; `on_interrupt` runs inside `interrupt()` /
        # `limit_exceeded()` before the task-group cancel propagates,
        # giving the binder a chance to clean up in-flight state that
        # anyio's hard cancel would otherwise bypass (notably the
        # `pending=True` flag on an in-flight `ModelEvent`).
        # `on_interrupt` receives a cause discriminator so the binder
        # records the right provenance — `"user_cancel"` for operator-
        # driven `interrupt()`, `"limit"` for `limit_exceeded()`,
        # `"system"` reserved for eval-shutdown paths. The values
        # mirror :attr:`InterruptEvent.source` so the binder can
        # forward straight through.
        self.on_complete: Callable[[], Awaitable[None]] | None = None
        self.on_interrupt: (
            Callable[[Literal["user_cancel", "limit", "system"]], None] | None
        ) = None

    @property
    def retries(self) -> int:
        """Number of prior failed attempts for this sample (0 on first run)."""
        return len(self.error_retries)

    def start(self, tg: TaskGroup) -> None:
        self.started = datetime.now(timezone.utc).timestamp()
        self.tg = tg

    def complete(self) -> None:
        self.completed = datetime.now(timezone.utc).timestamp()

    @property
    def pending_interaction(self) -> Literal["approval", "question"] | None:
        """Picker-visible pending state, derived from the counters.

        Approval wins over question when both are in flight — approvals
        gate tool execution, so they're the more urgent signal. The
        property reads while any matching wait remains, so concurrent
        ``parallel=True`` tool calls (which can fire multiple approvals
        for one sample) don't clear the indicator early.
        """
        if self._pending_approvals > 0:
            return "approval"
        if self._pending_questions > 0:
            return "question"
        return None

    @property
    def running_time(self) -> float:
        if self.started is not None:
            completed = (
                self.completed
                if self.completed is not None
                else datetime.now(timezone.utc).timestamp()
            )
            return completed - self.started
        else:
            return 0

    def interrupt(self, action: Literal["score", "error"]) -> None:
        self._interrupt_action = action
        if self.tg is None:
            raise RuntimeError(
                "Attempted to interrupt sample without enclosing task group."
            )
        self._fire_on_interrupt("user_cancel")
        self.tg.cancel_scope.cancel()

    def limit_exceeded(self, error: LimitExceededError) -> None:
        self._limit_exceeded_error = error
        if self.tg is None:
            raise RuntimeError(
                "Attempted to interrupt sample for limit without enclosing task group."
            )
        self._fire_on_interrupt("limit")
        self.tg.cancel_scope.cancel()

    def _fire_on_interrupt(
        self, cause: Literal["user_cancel", "limit", "system"]
    ) -> None:
        """Fire the registered ``on_interrupt`` hook, swallowing failures.

        The hook (set by whoever bound to this sample — in practice the
        live ACP session) cleans up in-flight state that anyio's hard
        cancel would otherwise bypass. ``cause`` lets the binder
        record the right provenance (e.g. an `InterruptEvent` with
        ``source="limit"`` for a token-limit hit, not ``"user_cancel"``).
        A failure inside the hook must not prevent the task-group
        cancel from firing, so we log and keep going. Sync because the
        cancel path is sync.
        """
        if self.on_interrupt is None:
            return
        try:
            self.on_interrupt(cause)
        except Exception:
            logger.warning(
                "ActiveSample on_interrupt hook raised; continuing with cancel",
                exc_info=True,
            )

    @property
    def interrupt_action(self) -> Literal["score", "error"] | None:
        return self._interrupt_action

    @property
    def limit_exceeded_error(self) -> LimitExceededError | None:
        return self._limit_exceeded_error


def init_active_samples() -> None:
    _active_samples.clear()


@contextlib.asynccontextmanager
async def active_sample(
    *,
    task: str,
    log_location: str,
    model: str,
    sample: Sample,
    epoch: int,
    message_limit: int | None,
    token_limit: int | None,
    cost_limit: float | None,
    time_limit: int | None,
    working_limit: int | None,
    fails_on_error: bool,
    transcript: Transcript,
    eval_id: str,
    checkpoint: ResolvedCheckpointConfig | None = None,
    resume_checkpoint: ResumeCheckpoint | None = None,
    eval_set_id: str | None = None,
    run_id: str | None = None,
    agent_name: str | None = None,
    error_retries: "list[EvalRetryError] | None" = None,
) -> AsyncGenerator[ActiveSample, None]:
    if sample.id is None:
        raise ValueError("active_sample requires sample.id to be set")
    # create the sample
    active = ActiveSample(
        task=task,
        log_location=log_location,
        model=model,
        sample=sample,
        epoch=epoch,
        message_limit=message_limit,
        token_limit=token_limit,
        cost_limit=cost_limit,
        time_limit=time_limit,
        working_limit=working_limit,
        sandboxes=await sandbox_connections(),
        fails_on_error=fails_on_error,
        transcript=transcript,
        checkpointer=create_checkpointer(
            config=checkpoint,
            log_location=log_location,
            sample_id=sample.id,
            epoch=epoch,
            resume_checkpoint=resume_checkpoint,
        ),
        eval_set_id=eval_set_id,
        run_id=run_id,
        eval_id=eval_id,
        agent_name=agent_name,
        error_retries=error_retries,
    )

    _active_samples.append(active)
    _sample_active.set(active)
    # Open the ACP session for this sample's lifetime. The session is the
    # ACP-specific transport layer (pub/sub, approver registry, transcript
    # snapshot, etc.); it produces into whatever agent_channel() is bound to
    # via maybe_bind/unbind. Local import to avoid a module-load-time cycle
    # (log → agent._acp → … → log).
    from inspect_ai.agent._acp.transport import acp_session

    try:
        async with acp_session():
            yield active
    finally:
        # Single "the sample is fully done" hook for whoever bound to
        # this sample. By the time we get here scoring + logging have
        # run and the task runner's ``emit_sample_end`` has fired, so
        # any registered binder (in practice the live ACP session)
        # can do its deferred teardown safely. Shielded so a
        # cancellation during teardown doesn't skip it.
        if active.on_complete is not None:
            with anyio.CancelScope(shield=True):
                try:
                    await active.on_complete()
                except Exception:
                    logger.warning(
                        "ActiveSample on_complete hook raised",
                        exc_info=True,
                    )
        active.complete()
        _active_samples.remove(active)
        _sample_active.set(None)


def sample_active() -> ActiveSample | None:
    return _sample_active.get(None)


def set_active_sample_token_limit(token_limit: int | None) -> None:
    active = sample_active()
    if active:
        active.token_limit = token_limit


def set_active_sample_total_tokens(total_tokens: int) -> None:
    active = sample_active()
    if active:
        active.total_tokens = total_tokens


def set_active_sample_cost_limit(cost_limit: float | None) -> None:
    active = sample_active()
    if active:
        active.cost_limit = cost_limit


def set_active_sample_total_cost(total_cost: float | None) -> None:
    active = sample_active()
    if active:
        active.total_cost = total_cost


def active_sample_message_limit() -> int | None:
    active = sample_active()
    if active:
        return active.message_limit
    else:
        return None


def set_active_sample_message_limit(message_limit: int | None) -> None:
    active = sample_active()
    if active:
        active.message_limit = message_limit


def set_active_sample_total_messages(total_messages: int) -> None:
    active = sample_active()
    if active:
        active.total_messages = total_messages


_active_model_event: ContextVar[ModelEvent | None] = ContextVar(
    "_active_model_event", default=None
)


@contextlib.contextmanager
def track_active_model_event(event: ModelEvent) -> Iterator[None]:
    token = _active_model_event.set(event)
    try:
        yield
    finally:
        _active_model_event.reset(token)


def has_active_model_event() -> bool:
    return _active_model_event.get() is not None


def set_active_model_event_call(
    request: Any,
    filter: "ModelCallFilter | None" = None,
) -> "ModelCall":
    """Create a ModelCall and register it with the active model event."""
    from inspect_ai.log._transcript import transcript
    from inspect_ai.model._model_call import ModelCall

    if request is None:
        request = {}
    model_call = ModelCall.create(request, None, filter)
    event = _active_model_event.get()
    if event is not None:
        event.call = model_call
        transcript()._event_updated(event)
    return model_call


def report_active_sample_retry() -> None:
    model_event = _active_model_event.get()
    if model_event is not None:
        if model_event.retries is None:
            model_event.retries = 0
        model_event.retries = model_event.retries + 1


_sample_active: ContextVar[ActiveSample | None] = ContextVar(
    "_sample_active", default=None
)


def active_samples() -> list[ActiveSample]:
    return _active_samples


_active_samples: list[ActiveSample] = []
