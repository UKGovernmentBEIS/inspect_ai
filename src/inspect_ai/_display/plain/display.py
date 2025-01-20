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
from ..core.panel import task_targets, task_title
from ..core.results import task_metric, tasks_results


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
                print("-" * 40)
                self._print_results()

    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        # Print task header
        print("\n" + "=" * 40)
        print(task_title(profile, show_model=True))

        # Print config and targets
        config = task_config(profile)
        if config:
            print(f"Config: {config}")
        targets = task_targets(profile)
        if targets:
            print(f"Dataset: {targets}")
        print("-" * 40)

        # Create and yield task display
        task = TaskWithResult(profile, None)
        self.tasks.append(task)
        yield PlainTaskDisplay(task)

    def _print_results(self) -> None:
        for task in self.tasks:
            if task.result:
                print(f"\nTask: {task_title(task.profile, show_model=True)}")

                # Print token usage stats
                if task.result.stats and task.result.stats.model_usage:
                    print("\nToken Usage:")
                    for model, usage in task.result.stats.model_usage.items():
                        total = usage.total_tokens
                        input = usage.input_tokens
                        output = usage.output_tokens
                        print(f"{model}: {total:,} tokens [I: {input:,}, O: {output:,}]")

                # Print evaluation results
                if task.result.results and task.result.results.scores:
                    print("\nScores:")
                    for score in task.result.results.scores:
                        for name, metric in score.metrics.items():
                            print(f"{name}: {metric.value:.3f}")


class PlainProgress(Progress):
    def __init__(self, total: int):
        self.total = total
        self.current = 0

    def update(self, n: int = 1) -> None:
        self.current += n
        percent = int(self.current / self.total * 100)
        print(f"\rProgress: {self.current}/{self.total} ({percent}%)", end="", flush=True)

    def complete(self) -> None:
        print("\rProgress: Complete (100%)")
        print()  # Add newline after completion


class PlainTaskDisplay(TaskDisplay):
    def __init__(self, task: TaskWithResult):
        self.task = task
        self.progress_display: PlainProgress | None = None
        self.samples_complete = 0
        self.samples_total = 0

    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]:
        self.progress_display = PlainProgress(self.task.profile.steps)
        yield self.progress_display

    def sample_complete(self, complete: int, total: int) -> None:
        self.samples_complete = complete
        self.samples_total = total
        print(f"\rSamples: {complete}/{total} ", end="", flush=True)

    def update_metrics(self, metrics: list[TaskDisplayMetric]) -> None:
        if metrics:
            # Print metrics on same line as samples
            metric_str = task_metric(metrics)
            print(f"| {metric_str}", end="", flush=True)

    def complete(self, result: TaskResult) -> None:
        self.task.result = result
        if self.progress_display:
            self.progress_display.complete()

        # Print final sample/metric status on new line
        if self.samples_total > 0:
            print(f"Final: {self.samples_complete}/{self.samples_total} samples processed")
