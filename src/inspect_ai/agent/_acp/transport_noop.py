"""No-op AcpTransport implementation.

Used as the default ContextVar value (so every ACP-unaware caller can
ask ``current_acp_transport()`` without isinstance guards) and as the
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
from inspect_ai.agent._acp.transport import _NOOP_SESSION_ID, AcpUpdate
from inspect_ai.model._chat_message import ChatMessageUser

if TYPE_CHECKING:
    from inspect_ai.agent._acp.transport import (
        AcpTransport,
        ApproverClient,
        ElicitationClient,
    )
    from inspect_ai.agent._channel import AgentChannel, AgentRef
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._tool import ToolEvent


class NoOpAcpTransport:
    """No-op session installed when ACP is not active or shadowed.

    ``attach()`` returns an already-closed receive stream so callers can
    still write transport code uniformly — the ``async for`` just exits
    immediately.
    """

    @property
    def session_id(self) -> str:
        """Always returns the ``"noop"`` sentinel."""
        return _NOOP_SESSION_ID

    async def __aenter__(self) -> AcpTransport:
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
        accepted to match :class:`LiveAcpTransport` but is discarded.
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

    def mark_active_session_client(self, client: object) -> None:
        """No-op: nothing to promote in the no-op session."""

    def approver_driver_chain(self) -> list[ApproverClient]:
        """No-op session returns an empty driver chain."""
        return []

    def attach_elicitation_client(
        self, client: ElicitationClient
    ) -> Callable[[], None]:
        """No-op attach — no elicitation clients can attach to the no-op session."""

        def _noop_unsubscribe() -> None:
            return None

        return _noop_unsubscribe

    def has_elicitation_clients(self) -> bool:
        """No-op session never has attached elicitation clients."""
        return False

    def has_ever_had_elicitation_client(self) -> bool:
        """No-op session never had elicitation clients."""
        return False

    def subscribe_elicitation_attach(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """No-op subscribe — no attaches can fire on the no-op session."""

        def _noop_unsubscribe() -> None:
            return None

        return _noop_unsubscribe

    def notify_elicitation_attach(self, client: ElicitationClient) -> None:
        """No-op: no subscribers can be registered on the no-op session."""

    def elicitation_driver_chain(self) -> list[ElicitationClient]:
        """No-op session returns an empty driver chain."""
        return []

    def maybe_bind(self, channel: AgentChannel, ref: AgentRef) -> bool:
        """No-op session never accepts a binder."""
        return False

    def unbind(self, ref: AgentRef) -> None:
        """No-op session has nothing to unbind."""
        return None

    @property
    def ref(self) -> AgentRef | None:
        """No-op session has no producer target."""
        return None

    @property
    def is_attachable(self) -> bool:
        """No-op sessions are never attachable."""
        return False
