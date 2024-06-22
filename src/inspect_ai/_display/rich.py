import asyncio
import contextlib
import datetime
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Callable, Iterator, Type

from rich.align import Align
from rich.console import Console, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    SpinnerColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)
from rich.progress import Progress as RProgress
from rich.table import Table
from rich.text import Text
from typing_extensions import override

from inspect_ai._util.path import cwd_relative_path
from inspect_ai._util.platform import is_running_in_jupyterlab, is_running_in_vscode
from inspect_ai.log import EvalError, EvalResults, EvalStats
from inspect_ai.log._log import rich_traceback
from inspect_ai.util._context.concurrency import concurrency_status
from inspect_ai.util._context.logger import logger_http_rate_limit_count

from ._display import Display, Progress, TaskDisplay, TaskProfile


@dataclass
class Theme:
    meta: str = "blue"
    light: str = "bright_black"
    metric: str = "green"
    link: str = "blue"
    error: str = "red"


class RichDisplay(Display):
    def __init__(self) -> None:
        self.console = rich_console()
        self.theme = Theme()

    @override
    def print(self, message: str) -> None:
        self.console.print(message, markup=False, highlight=False)

    @override
    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]:
        with rich_progress(self.console) as progress:
            yield RichProgress(total, progress)

    @override
    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        with Live(None, console=self.console) as live:
            # create task display
            display = RichTaskDisplay(
                profile,
                self.console,
                self.theme,
                lambda r: live.update(r, refresh=True),
            )

            # setup some timed updates (for when no progress ticks are occurring)
            loop = asyncio.get_event_loop()
            handle: asyncio.TimerHandle | None

            def update_display() -> None:
                display.on_update()
                nonlocal handle
                handle = loop.call_later(5, update_display)

            handle = loop.call_later(5, update_display)

            # yield the display
            yield display

            # cleanup handle if we need to
            if handle:
                handle.cancel()


# Note that use of rich progress seems to result in an extra
# empty cell after execution, see:
# https://github.com/Textualize/rich/issues/3211
# https://github.com/Textualize/rich/issues/3168


class RichProgress(Progress):
    def __init__(
        self,
        total: int,
        progress: RProgress,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        self.total = total
        self.progress = progress
        self.task_id = progress.add_task("", total=102)
        self.on_update = on_update

    @override
    def update(self, n: float = 1) -> None:
        advance = (n / self.total) * 100
        self.progress.update(task_id=self.task_id, advance=advance, refresh=True)
        if self.on_update:
            self.on_update()


class RichTaskDisplay(TaskDisplay):
    def __init__(
        self,
        profile: TaskProfile,
        console: Console,
        theme: Theme,
        render: Callable[[RenderableType], None],
    ) -> None:
        self.profile = profile
        self.console = console
        self.theme = theme
        self.progress_ui = rich_progress(console)
        self.render = render
        self.on_update()

    @override
    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]:
        yield RichProgress(total, self.progress_ui, self.on_update)

    @override
    def cancelled(self, samples_logged: int, stats: EvalStats) -> None:
        panel = self.task_panel(
            body=task_stats(self.profile, stats, self.theme),
            config=None,
            footer=task_interrupted(
                self.profile.log_location, samples_logged, self.theme
            ),
            log_location=self.profile.log_location,
        )
        self.render(panel)

    @override
    def summary(self, results: EvalResults, stats: EvalStats) -> None:
        panel = self.task_panel(
            body=task_stats(self.profile, stats, self.theme),
            config=None,
            footer=task_results(results, self.theme),
            log_location=self.profile.log_location,
        )
        self.render(panel)

    @override
    def error(
        self,
        samples_logged: int,
        error: EvalError,
        exc_type: Type[Any],
        exc_value: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        panel = self.task_panel(
            body=rich_traceback(exc_type, exc_value, traceback),
            config=None,
            footer=task_interrupted(
                self.profile.log_location, samples_logged, self.theme
            ),
            log_location=self.profile.log_location,
        )
        self.render(panel)

    def on_update(self) -> None:
        panel = self.task_panel(
            body=Align(self.progress_ui, vertical="middle"),
            config=task_config(self.profile, self.theme),
            footer=live_task_footer(self.theme),
            log_location=None,
        )
        self.render(panel)

    def task_panel(
        self,
        body: RenderableType,
        config: str | None,
        footer: tuple[RenderableType, RenderableType] | None,
        log_location: str | None,
    ) -> Panel:
        return task_panel(
            profile=self.profile,
            body=body,
            config=config,
            footer=footer,
            log_location=log_location,
            options=TaskPanelOptions(
                theme=self.theme,
                # rich doesn't detect vs code width properly
                width=(80 if is_vscode_notebook(self.console) else None),
                jupyter=self.console.is_jupyter,
            ),
        )


@dataclass
class TaskPanelOptions:
    theme: Theme
    width: int | None
    jupyter: bool


def task_panel(
    profile: TaskProfile,
    body: RenderableType,
    config: str | None,
    footer: tuple[RenderableType, RenderableType] | None,
    log_location: str | None,
    options: TaskPanelOptions,
) -> Panel:
    # alias theme
    theme = options.theme

    # setup table
    table = Table.grid(expand=True)
    table.add_column()
    table.add_column(justify="right")

    # main progress and task info
    table.add_row(
        body,
        Text(task_targets(profile), style=theme.meta),
    )

    # config
    if config:
        table.add_row(config)

    # footer if specified
    if footer:
        table.add_row()
        table.add_row(footer[0], footer[1])

    # enclose in outer table for log link footer
    root = table
    if log_location:
        # if we are in jupyter then use a real hyperlink
        if options.jupyter:
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
        title=f"[bold][{theme.meta}]{task_title(profile)}[/{theme.meta}][/bold]",
        title_align="left",
        width=options.width,
        expand=True,
    )
    return panel


def task_title(profile: TaskProfile) -> str:
    sequence = (
        f"task {profile.sequence[0]}/{profile.sequence[1]}: "
        if profile.sequence[1] > 1
        else ""
    )
    eval_epochs = profile.eval_config.epochs or 1
    epochs = f" x {profile.eval_config.epochs}" if eval_epochs > 1 else ""
    samples = f"{profile.samples//eval_epochs:,}{epochs} sample{'s' if profile.samples > 1 else ''}"
    title = f"{sequence}{profile.name} ({samples})"
    return title


def task_targets(profile: TaskProfile) -> str:
    return "   " + "\n   ".join(
        [str(profile.model), f"dataset: {profile.dataset}", f"scorer: {profile.scorer}"]
    )


def task_config(profile: TaskProfile, theme: Theme) -> str:
    # merge config
    config = (
        dict(profile.task_args)
        | dict(profile.eval_config.model_dump(exclude_none=True))
        | dict(profile.generate_config.model_dump(exclude_none=True))
    )
    config_print: list[str] = []
    for name, value in config.items():
        if name not in ["limit", "epochs"]:
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


def live_task_footer(theme: Theme) -> tuple[RenderableType, RenderableType]:
    return (
        f"[{theme.light}]{task_resources()}[/{theme.light}]",
        Text(task_http_rate_limits(), style=theme.light),
    )


def task_interrupted(
    log_location: str, samples_logged: int, theme: Theme
) -> tuple[RenderableType, RenderableType]:
    return (
        f"[bold][{theme.error}]Task interrupted ({samples_logged} "
        + "completed samples logged before interruption). "
        + f"Resume task with:[/{theme.error}][/bold]\n\n"
        + f"[bold][{theme.light}]inspect eval-retry {log_location}[/{theme.light}][/bold]",
        "",
    )


def task_results(
    results: EvalResults, theme: Theme
) -> tuple[RenderableType, RenderableType]:
    output: dict[str, str] = {}
    for name, metric in results.metrics.items():
        value = (
            "1.0"
            if metric.value == 1
            else (
                str(metric.value)
                if isinstance(metric.value, int)
                else f"{metric.value:.3g}"
            )
        )
        output[name] = value
    metrics = f"[{theme.metric}]{task_dict(output, True)}[/{theme.metric}]"

    return (metrics, "")


def task_stats(profile: TaskProfile, stats: EvalStats, theme: Theme) -> RenderableType:
    panel = Table.grid(expand=True)
    panel.add_column()
    config = task_config(profile, theme)
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
        table.add_row(
            Text(model, style="bold"),
            f"  {usage.total_tokens:,} tokens [{usage.input_tokens:,} + {usage.output_tokens:,}]",
            style=theme.light,
        )

    panel.add_row(table)
    return panel


def task_http_rate_limits() -> str:
    return f"HTTP rate limits: {logger_http_rate_limit_count():,}"


def task_dict(d: dict[str, str], bold_value: bool = False) -> str:
    slot1, slot2 = ("", "[/bold]") if bold_value else ("[/bold]", "")
    return "  ".join(
        [f"[bold]{key}:{slot1} {value}{slot2}" for key, value in d.items()]
    )


def rich_progress(console: Console) -> RProgress:
    return RProgress(
        SpinnerColumn(finished_text="✓"),
        BarColumn(bar_width=40 if is_vscode_notebook(console) else None),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        transient=True,
        console=console,
        expand=not is_vscode_notebook(console),
    )


def is_vscode_notebook(console: Console) -> bool:
    return console.is_jupyter and is_running_in_vscode()


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


_console: Console | None = None
_display: RichDisplay | None = None
