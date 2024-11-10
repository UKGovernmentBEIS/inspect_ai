import contextlib
from typing import Any, Coroutine, Iterator

import rich
from rich.console import Console
from typing_extensions import override

from ..core.display import (
    TR,
    Display,
    Progress,
    TaskDisplay,
    TaskProfile,
    TaskResult,
    TaskScreen,
    TaskWithResult,
)
from ..core.results import tasks_results
from .app import TaskScreenApp


class TextualDisplay(Display):
    def __init__(self) -> None:
        self.results: list[TaskWithResult] = []

    @override
    def print(self, message: str) -> None:
        pass

    @override
    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]:
        yield TextualProgress()

    @override
    def run_task_app(self, title: str, main: Coroutine[Any, Any, TR]) -> TR:
        # create and run the app
        app = TaskScreenApp[TR](title, main)
        app.run()

        # print tasks
        rich.print(tasks_results(self.results))

        # collect result
        result = app.result()

        # raise error as required
        if isinstance(result, BaseException):
            raise result

        # return result
        return result

    @override
    @contextlib.contextmanager
    def task_screen(self, total_tasks: int, parallel: bool) -> Iterator[TaskScreen]:
        yield TextualTaskScreen()

    @override
    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        yield TextualTaskDisplay(profile, self.results)


class TextualProgress(Progress):
    @override
    def update(self, n: int = 1) -> None:
        pass

    @override
    def complete(self) -> None:
        pass


class TextualTaskScreen(TaskScreen):
    def __init__(self) -> None: ...

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
    def __init__(self, profile: TaskProfile, results: list[TaskWithResult]) -> None:
        self.profile = profile
        self.results = results

    @override
    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]:
        yield TextualProgress()

    @override
    def complete(self, result: TaskResult) -> None:
        self.results.append(TaskWithResult(self.profile, result))
