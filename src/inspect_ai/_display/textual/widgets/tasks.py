import contextlib
from datetime import datetime
from typing import Iterator, cast

from rich.console import RenderableType
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ProgressBar, Static
from typing_extensions import override

from inspect_ai._display.core.results import task_metric
from inspect_ai._display.textual.widgets.clock import Clock
from inspect_ai._display.textual.widgets.task_detail import TaskDetail
from inspect_ai._display.textual.widgets.toggle import Toggle

from ...core.display import (
    Progress,
    TaskCancelled,
    TaskDisplay,
    TaskDisplayMetric,
    TaskError,
    TaskResult,
    TaskSpec,
    TaskWithResult,
)
from ...core.progress import (
    MAX_DESCRIPTION_WIDTH,
    MAX_MODEL_NAME_WIDTH,
    progress_count,
    progress_description,
    progress_model_name,
)

MAX_METRIC_WIDTH = 25
MAX_COUNT_WIDTH = 15


class TasksView(Container):
    DEFAULT_CSS = """
    TasksView {
        padding: 0 1;
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr auto;
        grid-rows: auto 1fr;
    }
    #tasks-progress {
        column-span: 2;
        scrollbar-size-vertical: 1;
        margin-top: 1;
        margin-bottom: 1;
    }
    #tasks-config {
        color: $text-muted;
    }
    #tasks-targets {
        text-align: right;
        color: $text-muted;
    }
    """

    config: reactive[RenderableType] = reactive("")
    targets: reactive[RenderableType] = reactive("")

    def __init__(self) -> None:
        super().__init__()
        self.description_width = MAX_DESCRIPTION_WIDTH
        self.model_name_width = MAX_MODEL_NAME_WIDTH
        self.sample_count_width = 0
        self.display_metrics = True

    def init_tasks(self, tasks: list[TaskSpec]) -> None:
        # clear existing tasks
        self.tasks.remove_children()

        # compute the column widths by looking all of the tasks
        self.description_width = min(
            max([len(task.name) for task in tasks]), MAX_DESCRIPTION_WIDTH
        )
        self.model_name_width = min(
            max([len(str(task.model)) for task in tasks]), MAX_MODEL_NAME_WIDTH
        )
        self.update_progress_widths()

    def add_task(self, task: TaskWithResult) -> TaskDisplay:
        self.update_count_width(task.profile.samples)
        task_display = TaskProgressView(
            task,
            self.description_width,
            self.model_name_width,
            self.sample_count_width,
            self.display_metrics,
        )
        self.tasks.mount(task_display)
        self.tasks.scroll_to_widget(task_display)
        self.update_progress_widths()

        return task_display

    def set_display_metrics(self, display_metrics: bool) -> None:
        self.display_metrics = display_metrics

    def update_count_width(self, samples: int) -> None:
        sample_count_str = progress_count(samples, samples, self.sample_count_width)
        self.sample_count_width = min(
            max(self.sample_count_width, len(sample_count_str)), MAX_COUNT_WIDTH
        )

    def update_progress_widths(self) -> None:
        progress_views = self.tasks.query_children(TaskProgressView)
        metrics_size = 0
        for progress_view in progress_views:
            metrics_size = max(
                metrics_size,
                progress_view.metrics_width
                if progress_view.metrics_width is not None
                else 0,
            )
        metrics_size = min(metrics_size, MAX_METRIC_WIDTH)

        for progress_view in progress_views:
            progress_view.update_metrics_width(metrics_size)
            progress_view.update_count_width(self.sample_count_width)

    def compose(self) -> ComposeResult:
        yield Static(id="tasks-config")
        yield Static(id="tasks-targets")
        yield ScrollableContainer(id="tasks-progress")

    def watch_config(self, new_config: RenderableType) -> None:
        tasks_config = cast(Static, self.query_one("#tasks-config"))
        tasks_config.update(new_config)

    def watch_targets(self, new_targets: RenderableType) -> None:
        tasks_targets = cast(Static, self.query_one("#tasks-targets"))
        tasks_targets.update(new_targets)

    @property
    def tasks(self) -> ScrollableContainer:
        return cast(ScrollableContainer, self.query_one("#tasks-progress"))


class TaskProgressView(Widget):
    DEFAULT_CSS = """
    TaskProgressView {
        height: auto;
        width: 1fr;
        layout: grid;
        grid-size: 8 2;
        grid-columns: auto auto auto auto 1fr auto auto auto;
        grid-rows: auto auto;
        grid-gutter: 0 1;
    }
    TaskProgressView Bar {
        width: 1fr;
        &> .bar--bar {
            color: $warning 90%;
        }
        &> .bar--complete {
            color: $success;
        }
    }
    #task-metrics {
        color:$text-secondary;
    }
    #task-detail {
        column-span: 8;
    }
    .hidden {
        display: none;
    }
    """

    def __init__(
        self,
        task: TaskWithResult,
        description_width: int,
        model_name_width: int,
        sample_count_width: int,
        display_metrics: bool,
    ) -> None:
        super().__init__()
        self.t = task

        self.description_width = description_width
        self.model_name_width = model_name_width

        self.progress_bar = ProgressBar(total=task.profile.steps, show_eta=False)
        self.count_display = Static()
        self.metrics_display = Static(id="task-metrics")
        self.task_progress = TaskProgress(self.progress_bar)

        self.toggle = Toggle()
        self.task_detail = TaskDetail(id="task-detail", classes="hidden")

        self.sample_count_width: int = sample_count_width
        self.display_metrics = display_metrics

    metrics: reactive[list[TaskDisplayMetric] | None] = reactive(None)
    metrics_width: reactive[int | None] = reactive(None)
    sample_count_width: reactive[int] = reactive(0)
    samples_complete: reactive[int] = reactive(0)
    samples_total: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        yield (self.toggle if self.display_metrics else Static())
        yield TaskStatusIcon()
        yield Static(
            progress_description(self.t.profile, self.description_width, pad=True)
        )
        yield Static(
            progress_model_name(self.t.profile.model, self.model_name_width, pad=True)
        )
        yield self.progress_bar
        yield self.count_display
        yield self.metrics_display
        yield Clock()
        yield self.task_detail

    @on(Toggle.Toggled)
    def handle_title_toggle(self, event: Toggle.Toggled) -> None:
        self.task_detail.hidden = not self.toggle.toggled
        event.stop()

    def on_mount(self) -> None:
        self.query_one(Clock).start(datetime.now().timestamp())

    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]:
        yield self.task_progress

    def complete(self, result: TaskResult) -> None:
        self.t.result = result
        try:
            self.query_one(TaskStatusIcon).result = result
            self.query_one(Clock).stop()
        except NoMatches:
            pass
        self.task_progress.complete()

    def sample_complete(self, complete: int, total: int) -> None:
        self.samples_complete = complete
        self.samples_total = total

    def update_metrics(self, metrics: list[TaskDisplayMetric]) -> None:
        self.metrics = metrics

    def update_metrics_width(self, width: int) -> None:
        self.metrics_width = width

    def update_count_width(self, width: int) -> None:
        self.sample_count_width = width

    def _watch_sample_count_width(self, width: int) -> None:
        self.refresh_count()

    def _watch_samples_complete(self, complete: int) -> None:
        self.refresh_count()

    def _watch_samples_total(self, total: int) -> None:
        self.refresh_count()

    def _watch_metrics_width(self, width: int) -> None:
        self.update_metrics_label()

    def _watch_metrics(self, metrics: list[TaskDisplayMetric] | None) -> None:
        if metrics is not None and len(metrics) > 0:
            # update label
            self.update_metrics_label()

            # update details
            self.task_detail.update_metrics(metrics)

    def refresh_count(self) -> None:
        progress_label = progress_count(
            self.samples_complete, self.samples_total, self.sample_count_width
        )
        self.count_display.update(progress_label)

    def update_metrics_label(self) -> None:
        # compute the label (with a min size)
        if self.metrics is not None and self.metrics_display is not None:
            metric_label = task_metric(self.metrics, self.metrics_width)
            self.metrics_width = len(metric_label)
            self.metrics_display.update(metric_label)


class TaskStatusIcon(Static):
    result: reactive[TaskResult | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self.watch_result(None)

    def watch_result(self, new_result: TaskResult | None) -> None:
        self.update(self._status_icon(new_result))

    def _status_icon(self, result: TaskResult | None) -> RenderableType:
        error = self.app.current_theme.error or ""
        succcess = self.app.current_theme.success or ""
        running = self.app.current_theme.secondary or ""
        if result:
            if isinstance(result, TaskError):
                return Text("✗", style=error)
            elif isinstance(result, TaskCancelled):
                return Text("✗", style=error)
            else:
                return Text("✔", style=succcess)
        else:
            return Text("⠿", style=running)


MAX_PROGRESS_PERCENT = 0.02
MIN_PROGRESS_PERCENT = 0.98


class TaskProgress(Progress):
    def __init__(self, progress_bar: ProgressBar) -> None:
        self.progress_bar = progress_bar
        self.current_progress = 0

        # always show a minimum amount of progress
        minimum_steps = (
            MAX_PROGRESS_PERCENT * progress_bar.total
            if progress_bar.total is not None
            else 0
        )
        self.progress_bar.update(progress=minimum_steps)

    @override
    def update(self, n: int = 1) -> None:
        self.current_progress = self.current_progress + n

        # enforce a maximum cap on task progress
        max_progress = (
            MIN_PROGRESS_PERCENT * self.progress_bar.total
            if self.progress_bar.total is not None
            else 0
        )
        if (
            self.current_progress > self.progress_bar.progress
            and self.current_progress < max_progress
        ):
            self.progress_bar.update(progress=self.current_progress)

    @override
    def complete(self) -> None:
        if self.progress_bar.total is not None:
            self.progress_bar.update(progress=self.progress_bar.total)
