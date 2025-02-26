import contextlib
from typing import Any, AsyncIterator, Coroutine, Iterator

import rich
from typing_extensions import override

from ..core.display import (
    TR,
    Display,
    Progress,
    TaskDisplay,
    TaskProfile,
    TaskScreen,
    TaskSpec,
)
from ..core.progress import RichProgress, rich_progress
from ..core.results import tasks_results
from .app import TaskScreenApp


class TextualDisplay(Display):
    @override
    def print(self, message: str) -> None:
        rich.get_console().print(message, markup=False, highlight=False)

    @override
    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]:
        with rich_progress() as progress:
            yield RichProgress(total, progress)

    @override
    def run_task_app(self, main: Coroutine[Any, Any, TR]) -> TR:
        # create and run the app
        self.app = TaskScreenApp[TR]()
        result = self.app.run_app(main)

        # print output
        if result.output:
            print("\n".join(result.output))

        # print tasks
        rich.print(tasks_results(result.tasks))

        # raise error as required
        if isinstance(result.value, BaseException):
            raise result.value

        # success! return value
        else:
            return result.value

    @override
    @contextlib.contextmanager
    def suspend_task_app(self) -> Iterator[None]:
        if getattr(self, "app", None) and self.app.is_running:
            with self.app.suspend_app():
                yield
        else:
            yield

    @override
    @contextlib.asynccontextmanager
    async def task_screen(
        self, tasks: list[TaskSpec], parallel: bool
    ) -> AsyncIterator[TaskScreen]:
        async with self.app.task_screen(tasks, parallel) as task_screen:
            yield task_screen

    @override
    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        with self.app.task_display(profile) as task_display:
            yield task_display
