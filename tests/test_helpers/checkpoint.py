"""Lightweight checkpointer test doubles."""

import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Literal, TypeVar

T = TypeVar("T")


@contextlib.asynccontextmanager
async def _noop_span() -> AsyncIterator[None]:
    yield


class RecordingCheckpointer:
    """Minimal in-memory `Checkpointer` for tests.

    Records the callbacks registered via `track()` so a test can fire a
    snapshot on demand (`cp.callbacks[key]()`), and optionally seeds
    `restored` state to simulate a resume. All lifecycle methods are inert,
    so it exercises agent/handler wiring without the real checkpointer's
    restic/transcript machinery.
    """

    def __init__(self, restored: dict[str, object] | None = None) -> None:
        self._restored = restored or {}
        self.callbacks: dict[str, Callable[[], object]] = {}

    @property
    def attempt(self) -> Literal["initial", "resume", "resume_for_scoring"]:
        return "resume" if self._restored else "initial"

    async def tick(self) -> None:
        return None

    async def checkpoint(self) -> None:
        return None

    def span_session(self) -> contextlib.AbstractAsyncContextManager[None]:
        return _noop_span()

    def track(
        self,
        key: str,
        callback: Callable[[], T],
        initial_value: T,
        *,
        value_type: type[T] | None = None,
    ) -> T:
        self.callbacks[key] = callback
        if key not in self._restored:
            return initial_value
        restored = self._restored[key]
        assert isinstance(restored, type(initial_value)), (
            f"restored {key!r} is {type(restored).__name__}, "
            f"expected {type(initial_value).__name__}"
        )
        return restored
