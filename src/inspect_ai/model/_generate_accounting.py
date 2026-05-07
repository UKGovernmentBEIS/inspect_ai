"""Per-call accounting for Model.generate() retry semantics."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from shortuuid import uuid

if TYPE_CHECKING:
    from inspect_ai.event._model import ModelEvent


@dataclass
class ModelGenerateAccounting:
    """Accumulates per-call counters and timing for one generate invocation."""

    call_id: str
    started_at: datetime
    working_start: float
    attempt_count: int = 0
    call_retry_count: int = 0
    http_retry_count: int = 0
    last_event: ModelEvent | None = None
    _terminal_finalized: bool = field(default=False, repr=False)

    @classmethod
    def new(
        cls, *, started_at: datetime, working_start: float
    ) -> ModelGenerateAccounting:
        """Create a new accounting context with a stable opaque call id."""
        return cls(call_id=uuid(), started_at=started_at, working_start=working_start)

    def register_event(self, event: ModelEvent) -> None:
        """Stamp call id and attempt on ``event`` and remember it."""
        self.attempt_count += 1
        event.call_id = self.call_id
        event.attempt = self.attempt_count
        self.last_event = event

    def record_call_retry(self) -> None:
        """Record one outer Tenacity retry that will actually be scheduled."""
        self.call_retry_count += 1

    def record_http_retry(self) -> None:
        """Record one provider/HTTP retry signal."""
        self.http_retry_count += 1

    def finalize_terminal_event(
        self, *, event: ModelEvent, completed_at: datetime, working_now: float
    ) -> None:
        """Set call-level fields on the terminal event. Idempotent."""
        if self._terminal_finalized:
            return
        self._terminal_finalized = True

        event.call_started_at = self.started_at
        event.call_completed_at = completed_at
        event.call_working_start = self.working_start
        event.call_working_time = max(0.0, working_now - self.working_start)
        event.call_retries = self.call_retry_count
        event.http_retries = self.http_retry_count
        event.retries = (
            self.http_retry_count
            if self.http_retry_count > 0
            else self.call_retry_count
        )


_accounting: ContextVar[ModelGenerateAccounting | None] = ContextVar(
    "_model_generate_accounting", default=None
)


def current_model_generate_accounting() -> ModelGenerateAccounting | None:
    """Return the current generate accounting context, if any."""
    return _accounting.get()


@contextlib.asynccontextmanager
async def model_generate_accounting(
    accounting: ModelGenerateAccounting,
) -> AsyncIterator[None]:
    """Set accounting for the current task and restore the previous value."""
    token = _accounting.set(accounting)
    try:
        yield
    finally:
        _accounting.reset(token)
