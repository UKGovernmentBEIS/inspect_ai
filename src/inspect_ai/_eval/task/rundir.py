import asyncio
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

from inspect_ai._eval.task.task import Task
from inspect_ai._eval.task.util import task_chdir

TASK_DIRECTORY_ATTRIB = "task_directory"

_task_chdir = ContextVar[str | None]("_task_chdir", default=None)

T = TypeVar("T", bound="asyncio.BaseEventLoop")


@contextmanager
def task_run_dir_switching() -> Iterator[None]:
    # get the beginning working dir
    cwd = os.getcwd()

    # get the class for the current event loop instance
    loop = asyncio.get_event_loop()
    if not isinstance(loop, asyncio.BaseEventLoop):
        raise ValueError(
            "Can't run tasks in multiple directories with loop of type %s" % type(loop)
        )
    cls: type[asyncio.BaseEventLoop] = loop.__class__

    # patch call_soon with directory switching version
    original_call_soon = cls.call_soon

    def patched_call_soon(
        self: T, callback: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> asyncio.Handle:
        wrapped_callback = _wrap_callback(callback)
        return original_call_soon(self, wrapped_callback, *args, **kwargs)

    cls.call_soon = patched_call_soon  # type: ignore

    # execute and restore original call_soon at the end
    try:
        yield
    finally:
        cls.call_soon = original_call_soon  # type: ignore
        os.chdir(cwd)


@contextmanager
def set_task_chdir(task: Task) -> Iterator[None]:
    chdir = task_chdir(task)
    if chdir is not None:
        token = _task_chdir.set(chdir)
        try:
            yield
        finally:
            _task_chdir.reset(token)
    else:
        yield


if sys.platform == "win32":
    BaseEventLoop = asyncio.ProactorEventLoop
else:
    BaseEventLoop = asyncio.SelectorEventLoop


def _wrap_callback(callback: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(callback)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        chdir = _task_chdir.get(None)
        if chdir is not None and chdir != os.getcwd():
            os.chdir(chdir)
        return callback(*args, **kwargs)

    return wrapper
