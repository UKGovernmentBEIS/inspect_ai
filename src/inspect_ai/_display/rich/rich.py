import asyncio
import contextlib
from dataclasses import dataclass
from typing import Callable, Iterator

import rich
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

from inspect_ai._util.ansi import no_ansi
from inspect_ai._util.constants import CONSOLE_DISPLAY_WIDTH
from inspect_ai._util.logger import http_rate_limit_count
from inspect_ai._util.throttle import throttle
from inspect_ai.log._transcript import InputEvent, transcript
from inspect_ai.util._concurrency import concurrency_status
from inspect_ai.util._trace import trace_enabled

from ..core.rich import (
    is_vscode_notebook,
    record_console_input,
    rich_initialise,
    rich_theme,
)
from ..display import (
    Display,
    Progress,
    TaskCancelled,
    TaskDisplay,
    TaskError,
    TaskProfile,
    TaskResult,
    TaskScreen,
    TaskWithResult,
)
from .config import task_config
from .panel import task_panel, task_title
from .progress import RichProgress
from .results import task_dict, tasks_results


@dataclass
class TaskStatus(TaskWithResult):
    progress: RProgress


class RichDisplay(Display):
    def __init__(self) -> None:
        self.total_tasks: int = 0
        self.tasks: list[TaskStatus] = []
        self.progress_ui: RProgress | None = None
        self.parallel = False
        self.live: Live | None = None
        self.timer_handle: asyncio.TimerHandle | None = None
        rich_initialise()

    @override
    def print(self, message: str) -> None:
        rich.get_console().print(message, markup=False, highlight=False)

    @override
    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]:
        with rich_progress() as progress:
            yield RichProgress(total, progress)

    @override
    @contextlib.contextmanager
    def task_screen(self, total_tasks: int, parallel: bool) -> Iterator[TaskScreen]:
        self.total_tasks = total_tasks
        self.tasks = []
        self.progress_ui = rich_progress()
        self.parallel = parallel
        try:
            with (
                Live(
                    None,
                    console=rich.get_console(),
                    transient=True,
                    auto_refresh=False,
                ) as live,
            ):
                # save reference to live
                self.live = live

                # enque a display update
                self.timer_handle = asyncio.get_event_loop().call_later(
                    1, self._update_display
                )

                # yield
                yield RichTaskScreen(live)

                # render task results (re-enable live if necessary)
                if not live.is_started:
                    live.start()
                live.transient = False
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
        # if there is no ansi display than all of the below will
        # be a no-op, so we print a simple text message for the task
        if no_ansi():
            rich.get_console().print(task_no_ansi(profile))

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
            and self.live.is_started
        ):
            if self.parallel:
                r = tasks_live_status(self.total_tasks, self.tasks, self.progress_ui)
            else:
                r = task_live_status(self.tasks, self.progress_ui)
            self.live.update(r, refresh=True)

        self.timer_handle = asyncio.get_event_loop().call_later(1, self._update_display)


class RichTaskScreen(TaskScreen):
    def __init__(self, live: Live) -> None:
        self.theme = rich_theme()
        self.live = live

    @override
    async def start(self) -> None:
        status_text = "Working" if trace_enabled() else "Task running"
        self.status = self.live.console.status(
            f"[{self.theme.meta} bold]{status_text}...[/{self.theme.meta} bold]",
            spinner="clock",
        )

    @override
    async def stop(self) -> None:
        self.status.stop()

    @override
    @contextlib.contextmanager
    def input_screen(
        self,
        header: str | None = None,
        transient: bool | None = None,
        width: int | None = None,
    ) -> Iterator[Console]:
        # determine transient based on trace mode
        if transient is None:
            transient = not trace_enabled()

        # clear live task status and transient status
        self.live.update("", refresh=True)
        self.status.stop()

        # show cursor for input
        self.live.console.show_cursor(True)

        # set width
        old_width: int | None = None
        if width:
            old_width = self.live.console.width
            self.live.console.width = min(old_width, width)

        # record console activity for event
        self.live.console.record = True

        try:
            # print header if requested
            if header:
                style = f"{rich_theme().meta} bold"
                self.live.console.rule(f"[{style}]{header}[/{style}]", style="black")
                self.live.console.print("")

            # yield the console
            with record_console_input():
                yield self.live.console

        finally:
            # capture recording then yield input event
            input = self.live.console.export_text(clear=False, styles=False)
            input_ansi = self.live.console.export_text(clear=True, styles=True)
            self.live.console.record = False
            transcript()._event(InputEvent(input=input, input_ansi=input_ansi))

            # print one blank line
            self.live.console.print("")

            # reset width
            if old_width:
                self.live.console.width = old_width

            # disable cursor while not collecting input
            self.live.console.show_cursor(False)

            # if transient then disable live updates entirely
            if transient is False and self.live.is_started:
                self.live.stop()

            # otherwise make sure they are enabled
            elif transient is True and not self.live.is_started:
                self.live.start()

            # if not transient then display mini-status
            if not transient:
                self.status.start()


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
    console = rich.get_console()
    width = CONSOLE_DISPLAY_WIDTH if is_vscode_notebook(console) else None

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


def task_no_ansi(profile: TaskProfile) -> str:
    message = f"Running task {task_title(profile, True)}"
    config = task_config(profile)
    if config:
        message = f"{message} (config: {config})"
    return f"{message}...\n"


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


def task_http_rate_limits() -> str:
    return f"HTTP rate limits: {http_rate_limit_count():,}"


def rich_progress() -> RProgress:
    console = rich.get_console()
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
