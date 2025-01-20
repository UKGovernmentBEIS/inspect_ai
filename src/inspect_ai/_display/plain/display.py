import contextlib
from typing import Any, Coroutine, Iterator, AsyncIterator

from ..core.display import (
    Display,
    Progress,
    TaskDisplay,
    TaskProfile,
    TaskScreen,
    TaskSpec, TR, TaskDisplayMetric, TaskResult,
)
import asyncio

class PlainDisplay(Display):
    def print(self, message: str) -> None:
        print(message)

    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]:
        yield PlainProgress(total)

    def run_task_app(self, main: Coroutine[Any, Any, TR]) -> TR:
        return asyncio.run(main)

    @contextlib.contextmanager
    def suspend_task_app(self) -> Iterator[None]:
        yield

    @contextlib.asynccontextmanager
    async def task_screen(
            self, tasks: list[TaskSpec], parallel: bool
    ) -> AsyncIterator[TaskScreen]:
        yield TaskScreen()

    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        yield PlainTaskDisplay(profile)


class PlainProgress(Progress):
    def __init__(self, total: int):
        self.total = total
        self.current = 0

    def update(self, n: int = 1) -> None:
        self.current += n
        print(f"\rProgress: {self.current}/{self.total} ({int(self.current / self.total * 100)}%)",
              end="", flush=True)

    def complete(self) -> None:
        print("\rProgress: Complete (100%)")


class PlainTaskDisplay(TaskDisplay):
    def __init__(self, profile: TaskProfile):
        self.profile = profile

    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]:
        yield PlainProgress(self.profile.steps)

    def sample_complete(self, complete: int, total: int) -> None:
        # Could add additional progress info here if desired
        pass

    def update_metrics(self, metrics: list[TaskDisplayMetric]) -> None:
        # Could add metrics display here if desired
        pass

    def complete(self, result: TaskResult) -> None:
        pass
