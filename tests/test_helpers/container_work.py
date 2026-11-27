"""Count the work container operations do in bridge and sentinel code, for linear-work tests."""

import sys
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

# operations whose work is their container's length: a list's `pop(0)` shifts
# every other element, and the rest may visit each one
_LINEAR: dict[type, tuple[str, ...]] = {
    list: ("pop", "remove", "index", "insert"),
    deque: ("remove", "index", "insert"),
}


@dataclass
class ContainerWork:
    work: int = 0


@contextmanager
def container_work() -> Iterator[ContainerWork]:
    """Count the elements C calls made from bridge and sentinel code may move or visit.

    A list's `pop`, `remove`, `index` and `insert`, and a deque's `remove`,
    `index` and `insert`, count their container's length; any other C call
    counts one. Counted from the C calls themselves, which a line tracer does
    not see. Per thread, so the code measured runs on this one.
    """
    counted = ContainerWork()

    def profile(frame: Any, event: str, arg: Any) -> None:
        if event != "c_call":
            return
        filename = frame.f_code.co_filename
        if "_bridge" not in filename and "_sentinel" not in filename:
            return
        container: Any = getattr(arg, "__self__", None)
        names = _LINEAR.get(type(container), ())
        if getattr(arg, "__name__", "") in names:
            counted.work += len(container)
        else:
            counted.work += 1

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        yield counted
    finally:
        sys.setprofile(previous)
