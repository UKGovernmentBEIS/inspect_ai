import contextlib
from typing import Iterator, cast

from rich.console import RenderableType
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import ProgressBar, Static
from typing_extensions import override

from ...core.display import (
    Progress,
    TaskDisplay,
    TaskResult,
    TaskWithResult,
)


class TasksView(Container):
    DEFAULT_CSS = """
    TasksView {
        padding: 0 1;
        layout: grid;
        grid-size: 2 3;
        grid-columns: 1fr auto;
        grid-rows: auto 1fr auto;
    }
    #tasks-progress {
        column-span: 2;
    }
    #tasks-targets {
        text-align: right;
    }
    #tasks-rate-limits {
        text-align: right;
    }

    """

    config: reactive[RenderableType] = reactive("")
    targets: reactive[RenderableType] = reactive("")
    footer: reactive[tuple[RenderableType, RenderableType]] = reactive(("", ""))

    def add_task(self, task: TaskWithResult) -> TaskDisplay:
        task_display = TaskProgressView(task)
        self.tasks.mount(task_display)
        return task_display

    def clear_tasks(self) -> None:
        self.tasks.remove_children()

    def compose(self) -> ComposeResult:
        yield Static(id="tasks-config")
        yield Static(id="tasks-targets")
        yield ScrollableContainer(id="tasks-progress")
        yield Static(id="tasks-resources")
        yield Static(id="tasks-rate-limits")

    def watch_config(self, new_config: RenderableType) -> None:
        tasks_config = cast(Static, self.query_one("#tasks-config"))
        tasks_config.update(new_config)

    def watch_targets(self, new_targets: RenderableType) -> None:
        tasks_targets = cast(Static, self.query_one("#tasks-targets"))
        tasks_targets.update(new_targets)

    def watch_footer(self, new_footer: tuple[RenderableType, RenderableType]) -> None:
        tasks_resources = cast(Static, self.query_one("#tasks-resources"))
        tasks_resources.update(new_footer[0])
        tasks_rate_limits = cast(Static, self.query_one("#tasks-rate-limits"))
        tasks_rate_limits.update(new_footer[1])

    @property
    def tasks(self) -> ScrollableContainer:
        return cast(ScrollableContainer, self.query_one("#tasks-progress"))


class TaskProgressView(Horizontal):
    DEFAULT_CSS = """
    TaskProgressView {
        height: auto;
    }
    """

    def __init__(self, task: TaskWithResult) -> None:
        super().__init__()
        self.t = task
        self.progress_bar = ProgressBar(total=task.profile.steps, show_eta=False)
        self.task_progress = TaskProgress(self.progress_bar)

    def compose(self) -> ComposeResult:
        yield self.progress_bar

    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]:
        yield self.task_progress

    def complete(self, result: TaskResult) -> None:
        self.t.result = result
        self.task_progress.complete()


class TaskProgress(Progress):
    def __init__(self, progress_bar: ProgressBar) -> None:
        self.progress_bar = progress_bar

    @override
    def update(self, n: int = 1) -> None:
        self.progress_bar.update(advance=n)

    @override
    def complete(self) -> None:
        if self.progress_bar.total is not None:
            self.progress_bar.update(progress=self.progress_bar.total)
