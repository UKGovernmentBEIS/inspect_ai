import os
import sys
from contextlib import AbstractContextManager, contextmanager
from copy import deepcopy
from pathlib import PurePath
from typing import Any, Iterator, overload


@contextmanager
def add_to_path(p: str) -> Iterator[None]:
    old_path = sys.path
    sys.path = sys.path[:]
    sys.path.insert(0, p)
    try:
        yield
    finally:
        sys.path = old_path


# NOTE: this code is adapted from
# https://github.com/python/cpython/blob/b3722ca058f6a6d6505cf2ea9ffabaf7fb6b6e19/Lib/contextlib.py#L767-L779)
class chdir(AbstractContextManager[None]):
    """Non thread-safe context manager to change the working directory.

    Changes the current working directory
    """

    def __init__(self, path: str):
        self.path = path
        self._old_cwd: list[str] = []

    def __enter__(self) -> None:
        self._old_cwd.append(os.getcwd())
        os.chdir(self.path)

    def __exit__(self, *excinfo: Any) -> None:
        os.chdir(self._old_cwd.pop())


class chdir_python(AbstractContextManager[None]):
    """Non thread-safe context manager to change the runtime Python directory.

    Changes the current working directory and adds the directory to
    the Python sys.path (so local module references resolve correctly).
    """

    def __init__(self, path: str):
        self.path = path
        self._old_sys_path: list[list[str]] = []
        self._old_cwd: list[str] = []

    def __enter__(self) -> None:
        self._old_cwd.append(os.getcwd())
        self._old_sys_path.append(deepcopy(sys.path))
        os.chdir(self.path)
        sys.path.append(self.path)

    def __exit__(self, *excinfo: Any) -> None:
        os.chdir(self._old_cwd.pop())
        sys.path = self._old_sys_path.pop()


@overload
def cwd_relative_path(file: str) -> str: ...


@overload
def cwd_relative_path(file: None) -> None: ...


def cwd_relative_path(file: str | None) -> str | None:
    if file:
        cwd = PurePath(os.getcwd())
        task_path = PurePath(file)
        if task_path.is_relative_to(cwd):
            return task_path.relative_to(cwd).as_posix()
        else:
            return file
    else:
        return None
