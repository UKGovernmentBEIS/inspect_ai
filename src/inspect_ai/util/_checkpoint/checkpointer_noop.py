import contextlib
from typing import Callable, Literal, TypeVar

from inspect_ai.util._checkpoint.checkpointer import Checkpointer
from inspect_ai.util._checkpoint.report import ResumeReport

T = TypeVar("T")


class _NoopCheckpointer(contextlib.AbstractAsyncContextManager[Checkpointer]):
    """No-op session — agent-facing API with all methods inert.

    Doubles as its own async ctx mgr so callers can store it where a
    setup is expected; ``__aenter__`` just returns ``self``.
    """

    def __init__(self) -> None:
        self._entered = False

    @property
    def attempt(self) -> Literal["initial", "resume", "resume_for_scoring"]:
        return "initial"

    @property
    def restored(self) -> ResumeReport | None:
        return None

    async def __aenter__(self) -> Checkpointer:
        self._entered = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._entered = False

    async def tick(self) -> None:
        return None

    async def checkpoint(self) -> None:
        return None

    def span_session(self) -> contextlib.AbstractAsyncContextManager[None]:
        return contextlib.nullcontext()

    def close(self) -> None:
        return None

    def current(self) -> Checkpointer | None:
        return self if self._entered else None

    def track(
        self,
        key: str,
        callback: Callable[[], T],
        initial_value: T,
        *,
        value_type: type[T] | None = None,
    ) -> T:
        return initial_value
