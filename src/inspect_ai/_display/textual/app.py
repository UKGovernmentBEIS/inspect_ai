import asyncio
import contextlib
from asyncio import CancelledError
from typing import Any, AsyncIterator, Coroutine, Generic, Iterator

import rich
from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult
from textual.events import Print
from textual.widgets import TabbedContent, TabPane
from textual.worker import Worker, WorkerState
from typing_extensions import override

from inspect_ai.log._samples import active_samples
from inspect_ai.log._transcript import InputEvent, transcript

from ..core.config import task_config
from ..core.display import (
    TR,
    TaskDisplay,
    TaskProfile,
    TaskScreen,
    TaskSpec,
    TaskWithResult,
)
from ..core.footer import task_footer
from ..core.panel import task_targets, task_title, tasks_title
from ..core.rich import record_console_input, rich_initialise, rich_theme
from .theme import inspect_dark, inspect_light
from .widgets.console import ConsoleView
from .widgets.footer import AppFooter
from .widgets.samples import SamplesView
from .widgets.tasks import TasksView
from .widgets.titlebar import AppTitlebar


class TaskScreenResult(Generic[TR]):
    def __init__(
        self,
        value: TR | BaseException,
        tasks: list[TaskWithResult],
        output: list[str],
    ) -> None:
        self.value = value
        self.tasks = tasks
        self.output = output


class TaskScreenApp(App[TR]):
    CSS_PATH = "app.tcss"

    def __init__(self) -> None:
        # call super
        super().__init__()

        # worker and output
        self._worker: Worker[TR] | None = None
        self._error: BaseException | None = None
        self._output: list[str] = []

        # task screen
        self._total_tasks = 0
        self._parallel = False
        self._tasks: list[TaskWithResult] = []

        # all tasks processed by app
        self._app_tasks: list[TaskWithResult] = []

        # enable rich hooks
        rich_initialise()

    def run_app(self, main: Coroutine[Any, Any, TR]) -> TaskScreenResult[TR]:
        # create the worker
        self._worker = self.run_worker(main, start=False, exit_on_error=False)

        # run the app
        self.run()

        # determine result value
        if self.return_value is not None:
            value: TR | BaseException = self.return_value
        elif self._error is not None:
            value = self._error
        else:
            value = CancelledError()

        # return result w/ output
        return TaskScreenResult(value=value, tasks=self._app_tasks, output=self._output)

    async def on_load(self) -> None:
        # events used to synchronise loading
        self._on_load_app = asyncio.Event()
        self._on_app_loaded = asyncio.Event()

        # run the workers
        self.workers.start_all()

        # wait until we are given the signal to load
        # if the worker completes in the meantime then there was an error during
        # initialisation, in that case return early, which will enable delivery of
        # the worker error event and standard exit control flow
        while not self._on_load_app.is_set():
            if len(self.workers._workers) == 0:
                return
            await asyncio.sleep(0.1)

    @contextlib.contextmanager
    def suspend_app(self) -> Iterator[None]:
        # suspend only if the app is already loaded
        # (otherwise its not yet displayed )
        if self._on_app_loaded.is_set():
            with self.app.suspend():
                try:
                    yield
                finally:
                    self.app.refresh(repaint=True)
        else:
            yield

    # exit the app when the worker terminates
    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.state == WorkerState.ERROR:
            self._error = event.worker.error
            self.exit(None, 1)
        elif event.worker.state == WorkerState.CANCELLED:
            self._error = CancelledError()
            self.exit(None, 1)
        elif event.worker.state == WorkerState.SUCCESS:
            self.exit(event.worker.result)

    # notification that a new top level set of tasks are being run
    @contextlib.asynccontextmanager
    async def task_screen(
        self, tasks: list[TaskSpec], parallel: bool
    ) -> AsyncIterator[TaskScreen]:
        # indicate its time to load then wait on the load
        self._on_load_app.set()
        await self._on_app_loaded.wait()

        # reset state
        self._tasks = []
        self._total_tasks = len(tasks)
        self._parallel = parallel

        # clear existing task progress
        tasks_view = self.query_one(TasksView)
        tasks_view.init_tasks(tasks)

        # update display
        self.update_display()

        # force repaint
        self.refresh(repaint=True)

        try:
            yield TextualTaskScreen(self)
        finally:
            self._tasks = []
            self._total_tasks = 0
            self._parallel = False

    # notification that a task is running and requires display
    @contextlib.contextmanager
    def task_display(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        # create and track task
        task = TaskWithResult(profile, None)
        self._app_tasks.append(task)
        self._tasks.append(task)

        # update display
        self.update_display()

        # add task
        try:
            yield self.query_one(TasksView).add_task(task)
        finally:
            pass

    # compose use
    def compose(self) -> ComposeResult:
        yield AppTitlebar()
        yield AppFooter()

        with TabbedContent(id="tabs", initial="tasks"):
            with TabPane("Tasks", id="tasks"):
                yield TasksView()
            with TabPane("Running Samples", id="samples"):
                yield SamplesView()
            with TabPane("Console", id="console"):
                yield ConsoleView()

    def on_mount(self) -> None:
        # register and set theme
        self.register_theme(inspect_dark)
        self.register_theme(inspect_light)
        self.theme = "inspect-dark"

        # capture stdout/stderr (works w/ on_print)
        self.begin_capture_print(self)

        # handle tab activations
        self.handle_tab_activations()

        # handle console unread
        self.handle_console_unread()

        # update display every second
        self.set_interval(1, self.update_display)

        # indicate that the app is loaded
        self._on_app_loaded.set()

    # update dynamic parts of display
    def update_display(self) -> None:
        self.update_title()
        self.update_tasks()
        self.update_samples()
        self.update_footer()

    # update the header title
    def update_title(self) -> None:
        # determine title
        if len(self._tasks) > 0:
            if self._parallel:
                completed = sum(1 for task in self._tasks if task.result is not None)
                title = f"{tasks_title(completed, self._total_tasks)}"
            else:
                title = f"{task_title(self._tasks[0].profile, show_model=len(self._tasks) == 1)}"
        else:
            title = ""

        # set if required
        header = self.query_one(AppTitlebar)
        if header.title != title:
            header.title = title

    def update_tasks(self) -> None:
        tasks = self.query_one(TasksView)
        if len(self._tasks) > 0:
            tasks.config = task_config(
                self._tasks[0].profile, generate_config=not self._parallel
            )
            if not self._parallel:
                tasks.targets = task_targets(self._tasks[0].profile)
            else:
                tasks.targets = " \n "
        else:
            tasks.config = ""
            tasks.targets = ""

    def update_samples(self) -> None:
        samples_view = self.query_one(SamplesView)
        samples_view.set_samples(active_samples())

    def update_footer(self) -> None:
        left, right = task_footer()
        footer = self.query_one(AppFooter)
        footer.left = left
        footer.right = right

    # track and display console unread state
    def handle_console_unread(self) -> None:
        # unread management
        tabs = self.query_one(TabbedContent)
        console_tab = tabs.get_tab("console")
        console_view = self.query_one(ConsoleView)

        def set_unread(unread: int | None) -> None:
            if unread is not None:
                console_tab.label = Text.from_markup(f"Console ({unread})")
            else:
                console_tab.label = Text.from_markup("Console")

        self.watch(console_view, "unread", set_unread)

    # handle tab activations
    def handle_tab_activations(self) -> None:
        tabs = self.query_one(TabbedContent)
        console_view = self.query_one(ConsoleView)
        samples_view = self.query_one(SamplesView)

        async def set_active_tab(active: str) -> None:
            await console_view.notify_active(active == "console")
            await samples_view.notify_active(active == "samples")

        self.watch(tabs, "active", set_active_tab)

    # capture output and route to console view and our buffer
    def on_print(self, event: Print) -> None:
        # remove trailing newline
        text = event.text
        if text.endswith("\n"):
            text = text[:-1]

        # track output (for printing at the end)
        self._output.append(text)

        # write to console view
        self.query_one(ConsoleView).write_ansi(text)

    # map ctrl+c to cancelling the worker
    @override
    async def action_quit(self) -> None:
        if self._worker and self._worker.is_running:
            self._worker.cancel()


class TextualTaskScreen(TaskScreen, Generic[TR]):
    def __init__(self, app: TaskScreenApp[TR]) -> None:
        self.app = app

    def __exit__(self, *excinfo: Any) -> None:
        pass

    @override
    @contextlib.contextmanager
    def input_screen(
        self,
        header: str | None = None,
        transient: bool | None = None,
        width: int | None = None,
    ) -> Iterator[Console]:
        with self.app.suspend_app():
            # get rich console
            console = rich.get_console()

            # set width
            old_width: int | None = None
            if width:
                old_width = console.width
                console.width = min(old_width, width)

            # record console activity for event
            console.record = True

            try:
                # print header if requested
                if header:
                    style = f"{rich_theme().meta} bold"
                    console.rule(f"[{style}]{header}[/{style}]", style="black")
                    console.print("")

                # yield the console
                with record_console_input():
                    yield console

            finally:
                # capture recording then yield input event
                input = console.export_text(clear=False, styles=False)
                input_ansi = console.export_text(clear=True, styles=True)
                console.record = False
                transcript()._event(InputEvent(input=input, input_ansi=input_ansi))

                # print one blank line
                console.print("")

                # reset width
                if old_width:
                    console.width = old_width
