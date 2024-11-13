from typing import cast

from rich.console import RenderableType
from textual.app import ComposeResult
from textual.containers import Container, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Static


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
