from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_task_init_env: ContextVar[dict[str, str] | None] = ContextVar(
    "sandbox_task_init_env", default=None
)


@contextmanager
def task_init_env(env: dict[str, str]) -> Iterator[None]:
    """Hold the variables `task_init_environment` returned around a `task_init` call.

    Setup does not write them to `os.environ`, so other coroutines and
    subprocesses do not see them. Docker's `task_init` reads them with
    `current_task_init_env()` and passes them to its compose commands.

    Args:
        env: Environment variables for this `task_init` call.
    """
    token = _task_init_env.set(env)
    try:
        yield
    finally:
        _task_init_env.reset(token)


def current_task_init_env() -> dict[str, str]:
    """Environment variables for the `task_init` call in progress (empty if none)."""
    return dict(_task_init_env.get() or {})
