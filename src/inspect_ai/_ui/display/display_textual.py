import contextlib
from typing import Iterator

import rich
from rich.console import Console
from typing_extensions import override

from .display import Display, Progress, TaskDisplay, TaskProfile, TaskResult, TaskScreen


class TextualDisplay(Display):
    @override
    def print(self, message: str) -> None:
        pass

    @override
    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]:
        yield TextualProgress()

    @override
    @contextlib.contextmanager
    def task_screen(self, total_tasks: int, parallel: bool) -> Iterator[TaskScreen]:
        yield TextualTaskScreen()

    @override
    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        yield TextualTaskDisplay()


class TextualProgress(Progress):
    @override
    def update(self, n: int = 1) -> None:
        pass

    @override
    def complete(self) -> None:
        pass


class TextualTaskScreen(TaskScreen):
    def __init__(self) -> None:
        pass

    @override
    async def start(self) -> None:
        pass

    @override
    async def stop(self) -> None:
        pass

    @override
    @contextlib.contextmanager
    def input_screen(
        self,
        header: str | None = None,
        transient: bool | None = None,
        width: int | None = None,
    ) -> Iterator[Console]:
        yield rich.get_console()


class TextualTaskDisplay(TaskDisplay):
    @override
    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]:
        yield TextualProgress()

    @override
    def complete(self, result: TaskResult) -> None:
        pass
