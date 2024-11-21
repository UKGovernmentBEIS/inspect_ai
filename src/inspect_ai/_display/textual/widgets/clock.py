from datetime import datetime

from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static

from inspect_ai._display.core.progress import progress_time


class Clock(Static):
    DEFAULT_CSS = """
    Clock {
        color: $primary-lighten-3;
    }
    """

    time: reactive[float] = reactive(datetime.now().timestamp)
    timer: Timer | None = None

    def __init__(self, interval: int = 1) -> None:
        super().__init__()
        self.start_time: float | None = None
        self.time = datetime.now().timestamp()
        self.interval = interval

    def start(self, start_time: float) -> None:
        if start_time != self.start_time:
            self.stop()
            self.start_time = start_time
            self.update_time()
            self.timer = self.set_interval(self.interval, self.update_time)

    def stop(self) -> None:
        self.start_time = None
        if self.timer:
            self.timer.stop()
            self.timer = None

    def on_unmount(self) -> None:
        self.stop()

    def watch_start_time(self, start_time: float | None) -> None:
        if start_time is not None:
            if self.timer is None:
                self.timer = self.set_interval(self.interval, self.update_time)
            self.update(progress_time(start_time))
        else:
            self.stop()

    def update_time(self) -> None:
        if self.start_time is not None:
            self.time = datetime.now().timestamp() - self.start_time

    def watch_time(self, time: float) -> None:
        self.update(progress_time(time))
