import contextlib
from typing import Callable, Literal, TypeVar

from inspect_ai.util._checkpoint.checkpointer import Checkpointer

T = TypeVar("T")


class _NoopCheckpointer(contextlib.AbstractAsyncContextManager[Checkpointer]):
    """No-op session — agent-facing API with all methods inert.

    Doubles as its own async ctx mgr so callers can store it where a
    setup is expected; ``__aenter__`` just returns ``self``.
    """

    @property
    def attempt(self) -> Literal["initial", "resume", "resume_for_scoring"]:
        return "initial"

    async def __aenter__(self) -> Checkpointer:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def tick(self) -> None:
        return None

    async def checkpoint(self) -> None:
        return None

    def span_session(self) -> contextlib.AbstractAsyncContextManager[None]:
        return contextlib.nullcontext()

    def close(self) -> None:
        return None

    def track(
        self,
        key: str,
        callback: Callable[[], T],
        initial_value: T,
        *,
        value_type: type[T] | None = None,
    ) -> T:
        return initial_value
