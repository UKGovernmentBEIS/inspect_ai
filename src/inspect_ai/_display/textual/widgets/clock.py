from datetime import datetime

from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static

from inspect_ai._display.core.progress import progress_time


class Clock(Static):
    DEFAULT_CSS = """
    Clock {
        color: $accent-lighten-3;
    }
    """

    start_time: reactive[float] = reactive(datetime.now().timestamp)
    time: reactive[float] = reactive(datetime.now().timestamp)
    timer: Timer | None = None

    def __init__(
        self, start_time: float = datetime.now().timestamp(), interval: int = 1
    ) -> None:
        super().__init__()
        self.start_time = start_time
        self.time = datetime.now().timestamp()
        self.interval = interval

    def complete(self) -> None:
        if self.timer:
            self.timer.stop()

    def on_mount(self) -> None:
        self.update_time()
        self.timer = self.set_interval(self.interval, self.update_time)

    def on_unmount(self) -> None:
        self.complete()

    def update_time(self) -> None:
        self.time = datetime.now().timestamp() - self.start_time

    def watch_time(self, time: float) -> None:
        self.update(progress_time(time))
