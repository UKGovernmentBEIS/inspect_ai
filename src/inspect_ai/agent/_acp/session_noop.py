"""No-op AcpSession implementation.

Used as the default ContextVar value (so every ACP-unaware caller can
ask ``current_acp_session()`` without isinstance guards) and as the
shadow installed inside a nested ``acp_session()`` block (so sub-agents
don't accidentally drive the outermost live session). All methods are
no-ops; ``session_id`` returns the ``"noop"`` sentinel; ``attach()``
returns an already-closed receive stream so transport code can iterate
uniformly across both implementations.
"""

from __future__ import annotations

import contextlib
from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable, Iterator, Literal, Sequence

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream

# Runtime imports: ``AcpUpdate`` is subscripted at runtime by
# ``anyio.create_memory_object_stream[AcpUpdate]`` inside ``attach()``;
# ``_NOOP_SESSION_ID`` is a string constant returned by ``session_id``.
from inspect_ai.agent._acp.session import _NOOP_SESSION_ID, AcpUpdate
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser

if TYPE_CHECKING:
    from inspect_ai.agent._acp.session import AcpSession, ApproverClient
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._tool import ToolEvent


class NoOpAcpSession:
    """No-op session installed when ACP is not active or shadowed.

    ``attach()`` returns an already-closed receive stream so callers can
    still write transport code uniformly — the ``async for`` just exits
    immediately.
    """

    @property
    def session_id(self) -> str:
        """Always returns the ``"noop"`` sentinel."""
        return _NOOP_SESSION_ID

    async def __aenter__(self) -> AcpSession:
        """No-op enter; returns ``self``."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """No-op exit."""
        return None

    def attach(self) -> MemoryObjectReceiveStream[AcpUpdate]:
        """Return an already-closed receive stream.

        Lets callers wire transport code identically against either
        variant — iterating the stream yields no updates and exits
        immediately.
        """
        send, receive = anyio.create_memory_object_stream[AcpUpdate](0)
        send.close()
        return receive

    def detach(self, stream: MemoryObjectReceiveStream[AcpUpdate]) -> None:
        """No-op detach."""
        return None

    def publish(self, update: AcpUpdate) -> None:
        """No-op publish — updates are discarded."""
        return None

    @contextlib.contextmanager
    def turn_scope(self) -> Iterator[None]:
        """No-op turn scope — yields once and exits without cancellation handling."""
        yield

    async def before_turn(
        self, messages: Sequence[ChatMessage]
    ) -> list[ChatMessageUser]:
        """No-op — never blocks, returns an empty list."""
        return []

    async def after_cancel(
        self, messages: list[ChatMessage] | None = None
    ) -> list[ChatMessage]:
        """No-op — never reachable on the no-op session (no cancel can fire)."""
        return []

    def submit_user_message(self, msg: ChatMessageUser) -> None:
        """No-op submit — message is discarded."""
        return None

    def cancel_current_turn(
        self,
        cause: Literal["user_cancel", "limit", "system"] = "user_cancel",
    ) -> None:
        """No-op cancel.

        Does not call ``record_interrupt_event`` — sub-agents must not
        emit cancel events into the top-level transcript. ``cause`` is
        accepted to match :class:`LiveAcpSession` but is discarded.
        """
        return None

    @contextlib.contextmanager
    def track_tool_call(
        self, tool_call_id: str, event: ToolEvent | None = None
    ) -> Iterator[None]:
        """No-op tool-call tracker — yields once."""
        yield

    @contextlib.contextmanager
    def track_model_event(self, event: ModelEvent) -> Iterator[None]:
        """No-op model-event tracker — yields once."""
        yield

    def subscribe_transcript_events(
        self, callback: Callable[[Any], None]
    ) -> Callable[[], None]:
        """No-op subscribe — there's no transcript to subscribe to.

        Returns a no-op unsubscribe callable so callers can use a
        uniform attach/detach pattern.
        """

        def _noop_unsubscribe() -> None:
            return None

        return _noop_unsubscribe

    def transcript_events_snapshot(self) -> Sequence[Any]:
        """No-op snapshot — empty sequence (nothing to replay)."""
        return []

    @property
    def interrupt_pending(self) -> bool:
        """No-op session never has a pending interrupt."""
        return False

    @property
    def agent_completed(self) -> bool:
        """No-op session has no lifecycle to complete."""
        return False

    def subscribe_interrupted(self, callback: Callable[[], None]) -> Callable[[], None]:
        """No-op subscribe — no cancels can fire on the no-op session."""

        def _noop_unsubscribe() -> None:
            return None

        return _noop_unsubscribe

    def subscribe_prompt_resolved(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """No-op subscribe — no prompts can be resolved on the no-op session."""

        def _noop_unsubscribe() -> None:
            return None

        return _noop_unsubscribe

    def attach_approver_client(self, client: ApproverClient) -> Callable[[], None]:
        """No-op attach — no approver clients can attach to the no-op session."""

        def _noop_unsubscribe() -> None:
            return None

        return _noop_unsubscribe

    def has_approver_clients(self) -> bool:
        """No-op session never has attached approver clients."""
        return False

    def has_ever_had_approver_client(self) -> bool:
        """No-op session never had approver clients."""
        return False

    def subscribe_approver_attach(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """No-op subscribe — no attaches can fire on the no-op session."""

        def _noop_unsubscribe() -> None:
            return None

        return _noop_unsubscribe

    def notify_approver_attach(self, client: ApproverClient) -> None:
        """No-op: no subscribers can be registered on the no-op session."""

    def mark_active_approver_client(self, client: ApproverClient) -> None:
        """No-op: nothing to promote in the no-op session."""

    def approver_driver_chain(self) -> list[ApproverClient]:
        """No-op session returns an empty driver chain."""
        return []
