"""Lightweight checkpointer test doubles."""

import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, TypeAdapter
from pydantic_core import to_jsonable_python

from inspect_ai.util import ResumeReport

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

    `snapshot()` captures the tracked state in JSON form, and a checkpointer
    created with `serialized=True` restores it through each key's
    `value_type`, as the real checkpointer does.
    """

    def __init__(
        self, restored: dict[str, object] | None = None, serialized: bool = False
    ) -> None:
        self._restored = restored or {}
        self._serialized = serialized
        self.callbacks: dict[str, Callable[[], object]] = {}

    def snapshot(self) -> dict[str, Any]:
        return {
            key: to_jsonable_python(callback())
            for key, callback in self.callbacks.items()
        }

    @property
    def attempt(self) -> Literal["initial", "resume", "resume_for_scoring"]:
        return "resume" if self._restored else "initial"

    @property
    def restored(self) -> ResumeReport | None:
        # Distinct from the ``restored`` ctor arg (seeded tracked state): this
        # is the on_resume report, which this double does not simulate.
        return None

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
        if self._serialized:
            if value_type is not None:
                return TypeAdapter(value_type).validate_python(restored)
            if isinstance(initial_value, BaseModel):
                return type(initial_value).model_validate(restored)
        assert isinstance(restored, type(initial_value)), (
            f"restored {key!r} is {type(restored).__name__}, "
            f"expected {type(initial_value).__name__}"
        )
        return restored
