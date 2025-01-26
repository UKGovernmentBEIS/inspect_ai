import asyncio
import contextlib
from typing import Any, AsyncIterator, Coroutine, Iterator

import rich

from inspect_ai._display.core.rich import rich_initialise
from inspect_ai._util.text import truncate
from inspect_ai._util.throttle import throttle

from ...util._concurrency import concurrency_status
from ..core.config import task_config
from ..core.display import (
    TR,
    Display,
    Progress,
    TaskDisplay,
    TaskDisplayMetric,
    TaskProfile,
    TaskResult,
    TaskScreen,
    TaskSpec,
    TaskWithResult,
)
from ..core.footer import task_http_rate_limits
from ..core.panel import task_panel, task_targets
from ..core.results import task_metric, tasks_results


class PlainDisplay(Display):
    def __init__(self) -> None:
        self.total_tasks: int = 0
        self.tasks: list[TaskWithResult] = []
        self.parallel = False
        rich_initialise()

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
        self.total_tasks = len(tasks)
        self.multiple_task_names = len({task.name for task in tasks}) > 1
        self.multiple_model_names = len({str(task.model) for task in tasks}) > 1
        self.tasks = []
        self.parallel = parallel
        try:
            # Print header for task(s)
            if parallel:
                print(f"Running {self.total_tasks} tasks...")
            yield TaskScreen()
        finally:
            # Print final results
            if self.tasks:
                self._print_results()

    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        # Print initial task information using a rich panel
        panel = task_panel(
            profile=profile,
            show_model=True,
            body="",  # Empty body since we haven't started yet
            subtitle=(task_config(profile), task_targets(profile)),
            footer=None,
            log_location=None,
        )
        rich.print(panel)

        # Create and yield task display
        task = TaskWithResult(profile, None)
        self.tasks.append(task)
        yield PlainTaskDisplay(
            task,
            show_task_names=self.multiple_task_names,
            show_model_names=self.multiple_model_names,
        )

    def _print_results(self) -> None:
        """Print final results using rich panels"""
        panels = tasks_results(self.tasks)
        rich.print(panels)


class PlainProgress(Progress):
    def __init__(self, total: int):
        self.total = total
        self.current = 0

    def update(self, n: int = 1) -> None:
        self.current += n
        # No direct printing - PlainTaskDisplay handles it

    def complete(self) -> None:
        self.current = self.total


class PlainTaskDisplay(TaskDisplay):
    def __init__(
        self, task: TaskWithResult, *, show_task_names: bool, show_model_names: bool
    ):
        self.task = task
        self.show_task_names = show_task_names
        self.show_model_names = show_model_names
        self.progress_display: PlainProgress | None = None
        self.samples_complete = 0
        self.samples_total = 0
        self.current_metrics: list[TaskDisplayMetric] | None = None
        self.last_progress = 0  # Track last progress percentage

    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]:
        self.progress_display = PlainProgress(self.task.profile.steps)
        yield self.progress_display

    @throttle(1)
    def _print_status_throttled(self) -> None:
        self._print_status()

    def _print_status(self) -> None:
        """Print status updates on new lines when there's meaningful progress"""
        if not self.progress_display:
            return

        # Calculate current progress percentage
        current_progress = int(
            self.progress_display.current / self.progress_display.total * 100
        )

        # Only print on percentage changes to avoid too much output
        if current_progress != self.last_progress:
            status_parts: list[str] = []

            # if this is parallel print task and model to distinguish (limit both to 12 chars)
            MAX_NAME_WIDTH = 12
            if self.show_task_names:
                status_parts.append(truncate(self.task.profile.name, MAX_NAME_WIDTH))
            if self.show_model_names:
                status_parts.append(
                    truncate(str(self.task.profile.model), MAX_NAME_WIDTH)
                )

            # Add step progress
            status_parts.append(
                f"Steps: {self.progress_display.current:3d}/{self.progress_display.total} {current_progress:3d}%"
            )

            # Add sample progress
            status_parts.append(
                f"Samples: {self.samples_complete:3d}/{self.samples_total:3d}"
            )

            # Add metrics
            if self.current_metrics:
                metric_str = task_metric(self.current_metrics)
                status_parts.append(metric_str)

            # Add resource usage
            # Very similar to ``inspect_ai._display.core.footer.task_resources``, but without
            # the rich formatting added in the ``task_dict`` call
            resources_dict: dict[str, str] = {}
            for model, resource in concurrency_status().items():
                resources_dict[model] = f"{resource[0]:2d}/{resource[1]:2d}"
            resources = ", ".join(
                [f"{key}: {value}" for key, value in resources_dict.items()]
            )
            status_parts.append(resources)

            # Add rate limits
            rate_limits = task_http_rate_limits()
            if rate_limits:
                status_parts.append(rate_limits)

            # Print on new line
            print(" | ".join(status_parts))

            self.last_progress = current_progress

    def sample_complete(self, complete: int, total: int) -> None:
        self.samples_complete = complete
        self.samples_total = total
        self._print_status_throttled()

    def update_metrics(self, metrics: list[TaskDisplayMetric]) -> None:
        self.current_metrics = metrics
        self._print_status_throttled()

    def complete(self, result: TaskResult) -> None:
        self.task.result = result
        self._print_status()
