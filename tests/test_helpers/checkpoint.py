"""Lightweight checkpointer test doubles."""

import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Literal, TypeVar

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
    snapshot on demand (`cp.callbacks[key]()`), counts ticks, and optionally
    seeds `restored` state to simulate a resume. All other lifecycle methods
    are inert, so it exercises agent/handler wiring without the real
    checkpointer's restic/transcript machinery.

    By default, `restored` values are live objects handed back as-is (a
    fast in-memory path). To exercise the same lossy JSON round-trip a real
    resume goes through, seed `restored` from `snapshot()` instead.
    """

    def __init__(self, restored: dict[str, object] | None = None) -> None:
        self._restored = restored or {}
        self.callbacks: dict[str, Callable[[], object]] = {}
        self.ticks = 0

    @property
    def attempt(self) -> Literal["initial", "resume", "resume_for_scoring"]:
        return "resume" if self._restored else "initial"

    @property
    def restored(self) -> ResumeReport | None:
        # Distinct from the ``restored`` ctor arg (seeded tracked state): this
        # is the on_resume report, which this double does not simulate.
        return None

    async def tick(self) -> None:
        self.ticks += 1

    async def checkpoint(self) -> None:
        return None

    def span_session(self) -> contextlib.AbstractAsyncContextManager[None]:
        return _noop_span()

    def snapshot(self) -> dict[str, object]:
        """Serialize every tracked value as the production checkpointer does at fire time.

        Mirrors `CheckpointerImpl`'s write path
        (`pydantic_core.to_jsonable_python`), so seeding a resumed
        `RecordingCheckpointer`'s `restored` from this crosses the same
        lossy JSON containers a real checkpoint file does (e.g. `set[str]`
        becomes a `list[str]`).
        """
        return {
            key: to_jsonable_python(callback())
            for key, callback in self.callbacks.items()
        }

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
        raw = self._restored[key]
        if value_type is not None:
            return TypeAdapter(value_type).validate_python(raw)
        if isinstance(initial_value, BaseModel):
            model: T = type(initial_value).model_validate(raw)
            return model
        assert isinstance(raw, type(initial_value)), (
            f"restored {key!r} is {type(raw).__name__}, "
            f"expected {type(initial_value).__name__}"
        )
        return raw
