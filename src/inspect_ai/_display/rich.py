import asyncio
import contextlib
import datetime
from dataclasses import dataclass
from typing import Callable, Iterator, Set

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.progress import Progress as RProgress
from rich.table import Table
from rich.text import Text
from typing_extensions import override

from inspect_ai._util.logger import http_rate_limit_count
from inspect_ai._util.path import cwd_relative_path
from inspect_ai._util.platform import is_running_in_jupyterlab, is_running_in_vscode
from inspect_ai._util.throttle import throttle
from inspect_ai.log import EvalResults, EvalStats
from inspect_ai.log._log import rich_traceback
from inspect_ai.util._concurrency import concurrency_status

from ._display import (
    Display,
    Progress,
    TaskCancelled,
    TaskDisplay,
    TaskError,
    TaskProfile,
    TaskResult,
    TaskSuccess,
)


@dataclass
class Theme:
    meta: str = "blue"
    light: str = "bright_black"
    metric: str = "green"
    link: str = "blue"
    success: str = "green"
    error: str = "red"


@dataclass
class TaskStatus:
    profile: TaskProfile
    result: TaskResult | None
    progress: RProgress


class RichDisplay(Display):
    def __init__(self) -> None:
        self.total_tasks: int = 0
        self.tasks: list[TaskStatus] = []
        self.progress_ui: RProgress | None = None
        self.parallel = False
        self.live: Live | None = None
        self.timer_handle: asyncio.TimerHandle | None = None

    @override
    def print(self, message: str) -> None:
        rich_console().print(message, markup=False, highlight=False)

    @override
    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]:
        with rich_progress() as progress:
            yield RichProgress(total, progress)

    @override
    @contextlib.contextmanager
    def live_task_status(self, total_tasks: int, parallel: bool) -> Iterator[None]:
        self.total_tasks = total_tasks
        self.tasks = []
        self.progress_ui = rich_progress()
        self.parallel = parallel
        try:
            with Live(None, console=rich_console(), auto_refresh=False) as live:
                # save reference to live
                self.live = live

                # enque a display update
                self.timer_handle = asyncio.get_event_loop().call_later(
                    1, self._update_display
                )

                # yield
                yield

                # render task results
                live.update(tasks_results(self.tasks), refresh=True)
        finally:
            # clear tasks and progress
            self.total_tasks = 0
            self.tasks = []
            self.progress_ui = None
            self.parallel = False
            self.live = None
            if self.timer_handle:
                self.timer_handle.cancel()

    @override
    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        # for typechekcer
        if self.tasks is None:
            self.tasks = []
        if self.progress_ui is None:
            self.progress_ui = rich_progress()

        status = TaskStatus(profile, None, self.progress_ui)
        self.tasks.append(status)
        self._update_display()
        yield RichTaskDisplay(
            status, show_name=self.parallel, on_update=self._update_display
        )

    @throttle(1)
    def _update_display(self) -> None:
        if (
            self.tasks is not None
            and self.tasks
            and self.progress_ui is not None
            and self.live is not None
        ):
            if self.parallel:
                r = tasks_live_status(self.total_tasks, self.tasks, self.progress_ui)
            else:
                r = task_live_status(self.tasks, self.progress_ui)
            self.live.update(r, refresh=True)

        self.timer_handle = asyncio.get_event_loop().call_later(1, self._update_display)


class RichTaskDisplay(TaskDisplay):
    def __init__(
        self,
        status: TaskStatus,
        show_name: bool,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        theme = rich_theme()
        self.status = status
        model = Text(str(self.status.profile.model))
        model.truncate(25, overflow="ellipsis")
        description = Text(f"{self.status.profile.name} " if show_name else "")
        if show_name:
            description.truncate(20, overflow="ellipsis")

        def task_status() -> str:
            if self.status.result:
                if isinstance(self.status.result, TaskError):
                    return f"[{theme.error}]✗[{theme.error}]"
                elif isinstance(self.status.result, TaskCancelled):
                    return f"[{theme.error}]✗[{theme.error}]"
                else:
                    return f"[{theme.success}]✔[{theme.success}]"
            else:
                return f"[{theme.meta}]⠿[{theme.meta}]"

        self.p = RichProgress(
            total=self.status.profile.steps,
            progress=self.status.progress,
            description=f"{description.markup}",
            model=f"{model.markup} ",
            status=task_status,
            on_update=on_update,
        )

    @override
    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]:
        yield self.p

    @override
    def complete(self, result: TaskResult) -> None:
        self.status.result = result
        self.p.complete()


# Note that use of rich progress seems to result in an extra
# empty cell after execution, see: https://github.com/Textualize/rich/issues/3274

PROGRESS_TOTAL = 102


class RichProgress(Progress):
    def __init__(
        self,
        total: int,
        progress: RProgress,
        description: str = "",
        model: str = "",
        status: Callable[[], str] | None = None,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        self.total = total
        self.progress = progress
        self.status = status if status else lambda: ""
        self.on_update = on_update
        self.task_id = progress.add_task(
            description, total=PROGRESS_TOTAL, model=model, status=self.status()
        )

    @override
    def update(self, n: int = 1) -> None:
        advance = (float(n) / float(self.total)) * 100
        self.progress.update(
            task_id=self.task_id, advance=advance, refresh=True, status=self.status()
        )
        if self.on_update:
            self.on_update()

    @override
    def complete(self) -> None:
        self.progress.update(
            task_id=self.task_id, completed=PROGRESS_TOTAL, status=self.status()
        )


def tasks_results(tasks: list[TaskStatus]) -> RenderableType:
    def render_task(task: TaskStatus) -> RenderableType:
        if isinstance(task.result, TaskCancelled):
            return task_result_cancelled(task.profile, task.result)
        elif isinstance(task.result, TaskError):
            return task_result_error(task.profile, task.result)
        elif isinstance(task.result, TaskSuccess):
            return task_result_summary(task.profile, task.result)
        else:
            return ""

    return Group(*[render_task(task) for task in tasks])


def task_live_status(tasks: list[TaskStatus], progress: RProgress) -> RenderableType:
    body: list[RenderableType] = ["", progress]
    config = task_config(tasks[0].profile)
    if config:
        body = [config] + body

    return task_panel(
        profile=tasks[0].profile,
        show_model=len(tasks) == 1,
        body=Group(*body),
        footer=live_task_footer(),
        log_location=None,
    )


def tasks_live_status(
    total_tasks: int, tasks: list[TaskStatus], progress: RProgress
) -> RenderableType:
    # rendering context
    theme = rich_theme()
    console = rich_console()
    width = 100 if is_vscode_notebook(console) else None

    # compute completed tasks
    completed = sum(1 for task in tasks if task.result is not None)

    # get config
    config = task_config(tasks[0].profile, generate_config=False)
    if config:
        config += "\n"

    # build footer table
    footer_table = Table.grid(expand=True)
    footer_table.add_column()
    footer_table.add_column(justify="right")
    footer = live_task_footer()
    footer_table.add_row()
    footer_table.add_row(footer[0], footer[1])

    # create panel w/ title
    panel = Panel(
        Group(config, progress, footer_table, fit=False),
        title=f"[bold][{theme.meta}]eval: {completed}/{total_tasks} tasks complete[/{theme.meta}][/bold]",
        title_align="left",
        width=width,
        expand=True,
    )
    return panel


def task_result_cancelled(
    profile: TaskProfile, cancelled: TaskCancelled
) -> RenderableType:
    return task_panel(
        profile=profile,
        show_model=True,
        body=task_stats(profile, cancelled.stats),
        footer=task_interrupted(profile, cancelled.samples_logged),
        log_location=profile.log_location,
    )


def task_result_summary(profile: TaskProfile, success: TaskSuccess) -> RenderableType:
    return task_panel(
        profile=profile,
        show_model=True,
        body=task_stats(profile, success.stats),
        footer=task_results(success.results),
        log_location=profile.log_location,
    )


def task_result_error(profile: TaskProfile, error: TaskError) -> RenderableType:
    return task_panel(
        profile=profile,
        show_model=True,
        body=rich_traceback(error.exc_type, error.exc_value, error.traceback),
        footer=task_interrupted(profile, error.samples_logged),
        log_location=profile.log_location,
    )


def task_panel(
    profile: TaskProfile,
    show_model: bool,
    body: RenderableType,
    footer: tuple[RenderableType, RenderableType] | None,
    log_location: str | None,
) -> Panel:
    # rendering context
    theme = rich_theme()
    console = rich_console()
    width = 100 if is_vscode_notebook(console) else None
    jupyter = console.is_jupyter

    # setup table
    table = Table.grid(expand=True)
    table.add_column()
    table.add_column(justify="right")

    # main progress and task info
    table.add_row(
        body,
        Text(task_targets(profile), style=theme.meta),
    )

    # footer if specified
    if footer:
        table.add_row()
        table.add_row(footer[0], footer[1])

    # enclose in outer table for log link footer
    root = table
    if log_location:
        # if we are in jupyter then use a real hyperlink
        if jupyter:
            log_location = f"[link={log_location}]{log_location}[/link]"

        # Print a cwd relative path
        try:
            log_location_relative = cwd_relative_path(log_location, walk_up=True)
        except ValueError:
            log_location_relative = log_location

        root = Table.grid(expand=True)
        root.add_column()
        root.add_row(table)
        root.add_row()
        root.add_row(
            f"[bold][{theme.light}]Log:[/{theme.light}][/bold] "
            + f"[{theme.link}]{log_location_relative}[/{theme.link}]"
        )

    # create panel w/ title
    panel = Panel(
        root,
        title=f"[bold][{theme.meta}]{task_title(profile, show_model)}[/{theme.meta}][/bold]",
        title_align="left",
        width=width,
        expand=True,
    )
    return panel


def task_title(profile: TaskProfile, show_model: bool) -> str:
    eval_epochs = profile.eval_config.epochs or 1
    epochs = f" x {profile.eval_config.epochs}" if eval_epochs > 1 else ""
    samples = f"{profile.samples//eval_epochs:,}{epochs} sample{'s' if profile.samples > 1 else ''}"
    title = f"{profile.name} ({samples})"
    if show_model:
        title = f"{title}: {profile.model}"
    return title


def task_targets(profile: TaskProfile) -> str:
    targets = [f"dataset: {profile.dataset}", f"scorer: {profile.scorer}"]
    return "   " + "\n   ".join(targets)


def task_config(profile: TaskProfile, generate_config: bool = True) -> str:
    # merge config
    theme = rich_theme()
    config = dict(profile.task_args) | dict(
        profile.eval_config.model_dump(exclude_none=True)
    )
    if generate_config:
        config = config | dict(profile.generate_config.model_dump(exclude_none=True))
    config_print: list[str] = []
    for name, value in config.items():
        if name not in ["limit", "epochs", "model"]:
            config_print.append(f"{name}: {value}")
    values = ", ".join(config_print)
    if values:
        return f"[{theme.light}]{values}[/{theme.light}]"
    else:
        return ""


def task_resources() -> str:
    resources: dict[str, str] = {}
    for model, resource in concurrency_status().items():
        resources[model] = f"{resource[0]}/{resource[1]}"
    return task_dict(resources)


@throttle(1)
def live_task_footer() -> tuple[RenderableType, RenderableType]:
    theme = rich_theme()
    return (
        f"[{theme.light}]{task_resources()}[/{theme.light}]",
        Text(task_http_rate_limits(), style=theme.light),
    )


def task_interrupted(
    profile: TaskProfile, samples_logged: int
) -> tuple[RenderableType, RenderableType]:
    log_location = profile.log_location
    theme = rich_theme()
    message = f"[bold][{theme.error}]Task interrupted ("
    if samples_logged > 0:
        message = (
            f"{message}{samples_logged} completed samples logged before interruption)."
        )
        if task_can_retry_from_filesystem(profile):
            message = (
                f"{message} Resume task with:[/{theme.error}][/bold]\n\n"
                + f"[bold][{theme.light}]inspect eval-retry {log_location}[/{theme.light}][/bold]"
            )
        else:
            message = f"{message}[/{theme.error}][/bold]"
    else:
        message = (
            f"{message}no samples completed before interruption)[/{theme.error}][/bold]"
        )

    return message, ""


def task_can_retry_from_filesystem(profile: TaskProfile) -> bool:
    return profile.file is not None


def task_results(results: EvalResults) -> tuple[RenderableType, RenderableType]:
    theme = rich_theme()
    # do we have more than one scorer name?
    scorer_names: Set[str] = {score.name for score in results.scores}
    reducer_names: Set[str] = {
        score.reducer for score in results.scores if score.reducer is not None
    }
    show_reducer = len(reducer_names) > 1 or "avg" not in reducer_names
    output: dict[str, str] = {}
    for score in results.scores:
        for name, metric in score.metrics.items():
            value = (
                "1.0"
                if metric.value == 1
                else (
                    str(metric.value)
                    if isinstance(metric.value, int)
                    else f"{metric.value:.3g}"
                )
            )
            name = (
                rf"{name}\[{score.reducer}]"
                if show_reducer and score.reducer is not None
                else name
            )
            key = f"{score.name}/{name}" if (len(scorer_names) > 1) else name
            output[key] = value

    metrics = f"[{theme.metric}]{task_dict(output, True)}[/{theme.metric}]"

    return (metrics, "")


def task_stats(profile: TaskProfile, stats: EvalStats) -> RenderableType:
    theme = rich_theme()
    panel = Table.grid(expand=True)
    panel.add_column()
    config = task_config(profile)
    if config:
        panel.add_row(config)
        panel.add_row()
    elif len(stats.model_usage) < 2:
        panel.add_row()

    table = Table.grid(expand=True)
    table.add_column(style="bold")
    table.add_column()

    # eval time
    started = datetime.datetime.fromisoformat(stats.started_at)
    completed = datetime.datetime.fromisoformat(stats.completed_at)
    elapsed = completed - started
    table.add_row(Text("total time:", style="bold"), f"  {elapsed}", style=theme.light)

    # token usage
    for model, usage in stats.model_usage.items():
        if (
            usage.input_tokens_cache_read is not None
            or usage.input_tokens_cache_write is not None
        ):
            input_tokens_cache_read = usage.input_tokens_cache_read or 0
            input_tokens_cache_write = usage.input_tokens_cache_write or 0
            input_tokens = f"[bold]I: [/bold]{usage.input_tokens:,}, [bold]CW: [/bold]{input_tokens_cache_write:,}, [bold]CR: [/bold]{input_tokens_cache_read:,}"
        else:
            input_tokens = f"[bold]I: [/bold]{usage.input_tokens:,}"

        table.add_row(
            Text(model, style="bold"),
            f"  {usage.total_tokens:,} tokens [{input_tokens}, [bold]O: [/bold]{usage.output_tokens:,}]",
            style=theme.light,
        )

    panel.add_row(table)
    return panel


def task_http_rate_limits() -> str:
    return f"HTTP rate limits: {http_rate_limit_count():,}"


def task_dict(d: dict[str, str], bold_value: bool = False) -> str:
    slot1, slot2 = ("", "[/bold]") if bold_value else ("[/bold]", "")
    return "  ".join(
        [f"[bold]{key}:{slot1} {value}{slot2}" for key, value in d.items()]
    )


def is_vscode_notebook(console: Console) -> bool:
    return console.is_jupyter and is_running_in_vscode()


def rich_theme() -> Theme:
    global _theme
    if _theme is None:
        _theme = Theme()
    return _theme


def rich_console() -> Console:
    global _console
    if _console is None:
        # only use color in vscode (other terminals are too
        # variable in their color contrast levels to rely on)
        use_color = is_running_in_vscode() and not is_running_in_jupyterlab()
        _console = Console(no_color=not use_color)
    return _console


def rich_display() -> RichDisplay:
    global _display
    if _display is None:
        _display = RichDisplay()
    return _display


def rich_progress() -> RProgress:
    console = rich_console()
    return RProgress(
        TextColumn("{task.fields[status]}"),
        TextColumn("{task.description}"),
        TextColumn("{task.fields[model]}"),
        BarColumn(bar_width=40 if is_vscode_notebook(console) else None),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        transient=True,
        console=console,
        expand=not is_vscode_notebook(console),
    )


_theme: Theme | None = None
_console: Console | None = None
_display: RichDisplay | None = None
