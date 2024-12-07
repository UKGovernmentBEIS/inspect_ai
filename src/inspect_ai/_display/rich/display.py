import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Coroutine, Iterator

import rich
from rich.console import Console, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress as RProgress
from rich.table import Table
from typing_extensions import override

from inspect_ai._util.constants import CONSOLE_DISPLAY_WIDTH
from inspect_ai._util.display import display_type
from inspect_ai._util.throttle import throttle
from inspect_ai.log._transcript import InputEvent, transcript
from inspect_ai.util._trace import trace_enabled

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
from ..core.footer import task_footer
from ..core.panel import task_panel, task_targets, task_title, tasks_title
from ..core.progress import (
    RichProgress,
    progress_description,
    progress_model_name,
    progress_status_icon,
    rich_progress,
)
from ..core.results import task_metric, tasks_results
from ..core.rich import (
    is_vscode_notebook,
    record_console_input,
    rich_initialise,
    rich_theme,
)


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
    def run_task_app(self, main: Coroutine[Any, Any, TR]) -> TR:
        return asyncio.run(main)

    @override
    @contextlib.contextmanager
    def suspend_task_app(self) -> Iterator[None]:
        yield

    @override
    @contextlib.asynccontextmanager
    async def task_screen(
        self, tasks: list[TaskSpec], parallel: bool
    ) -> AsyncIterator[TaskScreen]:
        self.total_tasks = len(tasks)
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
                with RichTaskScreen(live) as task_screen:
                    self.live = live

                    # enque a display update
                    self.timer_handle = asyncio.get_event_loop().call_later(
                        1, self._update_display
                    )

                    # yield
                    yield task_screen

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
        if display_type() == "plain":
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
        status_text = "Working" if trace_enabled() else "Task running"
        self.status = self.live.console.status(
            f"[{self.theme.meta} bold]{status_text}...[/{self.theme.meta} bold]",
            spinner="clock",
        )

    def __exit__(self, *excinfo: Any) -> None:
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
        self.status = status
        model = progress_model_name(self.status.profile.model)
        description = progress_description(self.status.profile)

        def task_status() -> str:
            return progress_status_icon(self.status.result)

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
    def sample_complete(self, complete: int, total: int) -> None:
        self.p.update_count(complete, total)

    @override
    def update_metrics(self, metrics: list[TaskDisplayMetric]) -> None:
        if len(metrics) > 0:
            self.p.update_score(task_metric(metrics))

    @override
    def complete(self, result: TaskResult) -> None:
        self.status.result = result
        self.p.complete()


def task_live_status(tasks: list[TaskStatus], progress: RProgress) -> RenderableType:
    theme = rich_theme()

    # the panel contents
    config = task_config(tasks[0].profile, style=theme.light)
    targets = task_targets(tasks[0].profile)
    subtitle = config, targets

    # the panel
    return task_panel(
        profile=tasks[0].profile,
        show_model=len(tasks) == 1,
        body=progress,
        subtitle=subtitle,
        footer=task_footer(theme.light),
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
    config = task_config(tasks[0].profile, generate_config=False, style=theme.light)
    if config:
        config += "\n"

    # build footer table
    footer_table = Table.grid(expand=True)
    footer_table.add_column()
    footer_table.add_column(justify="right")
    footer = task_footer(theme.light)
    footer_table.add_row()
    footer_table.add_row(footer[0], footer[1])

    # build a layout table
    layout_table = Table.grid(expand=True)
    layout_table.add_column()
    layout_table.add_row(config)
    layout_table.add_row(progress)
    layout_table.add_row(footer_table)

    # create panel w/ title
    panel = Panel(
        layout_table,
        title=f"[bold][{theme.meta}]{tasks_title(completed, total_tasks)}[/{theme.meta}][/bold]",
        title_align="left",
        width=width,
        expand=True,
    )
    return panel


def task_no_ansi(profile: TaskProfile) -> str:
    theme = rich_theme()
    message = f"Running task {task_title(profile, True)}"
    config = task_config(profile, style=theme.light)
    if config:
        message = f"{message} (config: {config})"
    return f"{message}...\n"
