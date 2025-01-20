import asyncio
import contextlib
from typing import Any, AsyncIterator, Coroutine, Iterator

from ..core.config import task_config
from ..core.display import (
    Display,
    Progress,
    TaskDisplay,
    TaskDisplayMetric,
    TaskProfile,
    TaskResult,
    TaskScreen,
    TaskSpec,
    TaskWithResult, TR,
)
from ..core.footer import task_footer
from ..core.panel import task_targets, task_title, task_panel
from ..core.results import task_metric, tasks_results, task_stats
import rich

class PlainDisplay(Display):
    def __init__(self) -> None:
        self.total_tasks: int = 0
        self.tasks: list[TaskWithResult] = []
        self.parallel = False

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
                print("\nResults:")
                self._print_results()

    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        # Print initial task information using a rich panel
        panel = task_panel(
            profile=profile,
            show_model=True,
            body="",  # Empty body since we haven't started yet
            subtitle=(
                task_config(profile),
                task_targets(profile)
            ),
            footer=None,
            log_location=None,
        )
        print("\n")
        rich.print(panel)
        print("\n")  # Add space before progress starts

        # Create and yield task display
        task = TaskWithResult(profile, None)
        self.tasks.append(task)
        yield PlainTaskDisplay(task)

    def _print_results(self) -> None:
        """Print final results using rich panels"""
        for task in self.tasks:
            if task.result:
                # Use rich panel for final summary
                panel = task_panel(
                    profile=task.profile,
                    show_model=True,
                    body=task_stats(task.result.stats),
                    subtitle=(
                        task_config(task.profile),
                        task_targets(task.profile)
                    ),
                    footer=task_footer(),
                    log_location=task.profile.log_location
                )
                print("\n")
                rich.print(panel)


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
    def __init__(self, task: TaskWithResult):
        self.task = task
        self.progress_display: PlainProgress | None = None
        self.samples_complete = 0
        self.samples_total = 0
        self.current_metrics: list[TaskDisplayMetric] | None = None
        print()  # Blank line for progress

    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]:
        self.progress_display = PlainProgress(self.task.profile.steps)
        yield self.progress_display

    def _print_status(self) -> None:
        # Build status line
        status_parts = []

        # Add step progress
        if self.progress_display:
            percent = int(self.progress_display.current / self.progress_display.total * 100)
            status_parts.append(
                f"Steps: {self.progress_display.current}/{self.progress_display.total} ({percent}%)")

        # Add sample progress
        status_parts.append(f"Samples: {self.samples_complete}/{self.samples_total}")

        # Add metrics
        if self.current_metrics:
            metric_str = task_metric(self.current_metrics)
            status_parts.append(metric_str)

        # Print single status line with carriage return
        print(f"\r{' | '.join(status_parts)}", end="", flush=True)

    def sample_complete(self, complete: int, total: int) -> None:
        self.samples_complete = complete
        self.samples_total = total
        self._print_status()

    def update_metrics(self, metrics: list[TaskDisplayMetric]) -> None:
        self.current_metrics = metrics
        self._print_status()

    def complete(self, result: TaskResult) -> None:
        self.task.result = result
        print()  # New line after progress
        print("Task complete.")

        # Print final status
        if self.samples_total > 0:
            print(f"Final: {self.samples_complete}/{self.samples_total} samples processed")
            if self.current_metrics:
                metric_str = task_metric(self.current_metrics)
                print(f"Metrics: {metric_str}")