import asyncio
import contextlib
from asyncio import CancelledError
from typing import Any, AsyncIterator, ClassVar, Coroutine, Generic, Iterator, cast

import rich
from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.css.query import NoMatches
from textual.events import Print
from textual.widgets import TabbedContent, TabPane
from textual.widgets.tabbed_content import ContentTabs
from textual.worker import Worker, WorkerState
from typing_extensions import override

from inspect_ai._display.core.textual import textual_enable_mouse_support
from inspect_ai._util.html import as_html_id
from inspect_ai.log._samples import active_samples
from inspect_ai.log._transcript import InputEvent, transcript

from ...util._panel import InputPanel
from ..core.config import task_config
from ..core.display import (
    TP,
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

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding(
            "ctrl+c",
            "quit",
            "Interrupt",
            tooltip="Interrupt the app and return to the command prompt.",
            show=False,
            priority=True,
        )
    ]

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

    def _watch_app_focus(self, focus: bool) -> None:
        super()._watch_app_focus(focus)

        if focus and self.app._driver:
            textual_enable_mouse_support(self.app._driver)

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
            task_view = self.query_one(TasksView)
            task_view.set_display_metrics(
                profile.eval_config.score_display is not False
            )
            yield task_view.add_task(task)
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
        for input_panel in self.query(f".{InputPanel.DEFAULT_CLASSES}"):
            cast(InputPanel, input_panel).update()

    # update the header title
    def update_title(self) -> None:
        # determine title
        if self._worker and self._worker.is_cancelled:
            title = "eval interrupted (cancelling running samples...)"
        elif len(self._tasks) > 0:
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

    # activate the tasks tab
    def activate_tasks_tab(self) -> None:
        tasks = self.query_one(TasksView)
        tasks.tasks.focus()  # force the tab to switch by focusing a child
        self.query_one(ContentTabs).focus()  # focus the tab control

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
        if self._worker and self._worker.is_running and not self._worker.is_cancelled:
            self._worker.cancel()
            self.update_title()

    # dynamic input panels
    async def add_input_panel(self, title: str, panel: InputPanel) -> None:
        tabs = self.query_one(TabbedContent)
        await tabs.add_pane(TabPane(title, panel, id=as_input_panel_id(title)))

    def get_input_panel(self, title: str) -> InputPanel | None:
        try:
            tab_pane = self.query_one(f"#{as_input_panel_id(title)}")
            if len(tab_pane.children) > 0:
                return cast(InputPanel, tab_pane.children[0])
            else:
                return None
        except NoMatches:
            return None

    async def remove_input_panel(self, title: str) -> None:
        tabs = self.query_one(TabbedContent)
        await tabs.remove_pane(as_html_id(as_input_panel_id(title), title))

    class InputPanelHost(InputPanel.Host):
        def __init__(self, app: "TaskScreenApp[TR]", tab_id: str) -> None:
            self.app = app
            self.tab_id = tab_id

        def set_title(self, title: str) -> None:
            tabs = self.app.query_one(TabbedContent)
            tab = tabs.get_tab(self.tab_id)
            tab.label = Text.from_markup(title)

        def activate(self) -> None:
            # show the tab
            tabs = self.app.query_one(TabbedContent)
            tabs.show_tab(self.tab_id)

            # focus the first focuable child (this seems to be necessary
            # to get textual to reliably make the switch). after that, focus
            # the tabs control so the user can switch back w/ the keyboard
            tab_pane = self.app.query_one(f"#{self.tab_id}")
            panel = cast(InputPanel, tab_pane.children[0])
            for child in panel.children:
                if child.focusable:
                    child.focus()
                    self.app.query_one(ContentTabs).focus()
                    break

        def deactivate(self) -> None:
            tabs = self.app.query_one(TabbedContent)
            if tabs.active == self.tab_id:
                self.app.activate_tasks_tab()

        def close(self) -> None:
            tabs = self.app.query_one(TabbedContent)
            tabs.remove_pane(self.tab_id)
            self.app.activate_tasks_tab()


class TextualTaskScreen(TaskScreen, Generic[TR]):
    def __init__(self, app: TaskScreenApp[TR]) -> None:
        self.app = app
        self.lock = asyncio.Lock()

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

    @override
    async def input_panel(self, title: str, panel: type[TP]) -> TP:
        async with self.lock:
            panel_widget = self.app.get_input_panel(title)
            if panel_widget is None:
                panel_widget = panel(
                    title,
                    TaskScreenApp[TR].InputPanelHost(
                        self.app, as_input_panel_id(title)
                    ),
                )
                await self.app.add_input_panel(title, panel_widget)
            return cast(TP, panel_widget)


def as_input_panel_id(title: str) -> str:
    return as_html_id("id-input-panel", title)
