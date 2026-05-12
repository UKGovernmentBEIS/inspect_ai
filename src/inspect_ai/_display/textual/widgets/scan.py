"""Textual widget rendering the scout scan-progress view from `ScanDisplayState`.

Reads the in-memory state populated by `scan_init` / `scan_eval_sample`
and composes scout's `scanners_table(spec, summary)` underneath a
progress bar. Deliberately bypasses scout's `scan_panel` — the Textual
app already has its own footer (model-provider connections, HTTP
retries) and we don't want the duplicate footer or the surrounding
panel border.

A persistent `rich.progress.Progress` is kept on the widget so its
`TimeElapsedColumn` / `TimeRemainingColumn` accumulate correctly across
ticks (creating a fresh Progress per render would reset elapsed time
to zero each second).
"""

from typing import cast

from rich.console import Group, RenderableType
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from inspect_ai._eval.task.scan_display import get_state


class ScanView(Container):
    DEFAULT_CSS = """
    ScanView {
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="scan-panel", markup=False)

    def update(self, samples_total: int = 0) -> None:
        """Read the latest ScanDisplayState and re-render the panel.

        `samples_total` is the expected total scan count (samples ×
        scanners). When 0, the progress bar is omitted and only the
        scanner-stats table renders.
        """
        state = get_state()
        target = cast(Static, self.query_one("#scan-panel"))

        if not state.active or state.spec is None or state.summary is None:
            target.update("(no scan in progress)")
            return

        # imported lazily so inspect_ai doesn't pull scout into module
        # import time — scout is an optional dep
        from inspect_scout._display.rich import scanners_table

        progress = self._progress_for(samples_total, state.samples_completed)
        table = scanners_table(state.spec, state.summary)
        renderable: RenderableType = (
            Group("", progress, "", table) if progress is not None else table
        )
        target.update(renderable)

    def _progress_for(
        self, samples_total: int, samples_completed: int
    ) -> Progress | None:
        """Return a persistent `Progress` updated with the latest counts.

        Returns `None` when `samples_total == 0` (caller hasn't computed
        a total yet, e.g. tasks haven't fully resolved). Rich `Progress`
        renders its elapsed/remaining columns at draw time from the
        task's start time, so reusing the instance keeps those readings
        meaningful across ticks.
        """
        if samples_total <= 0:
            return None

        if self._progress is None:
            self._progress = Progress(
                TextColumn("Scanning"),
                BarColumn(bar_width=None),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            )
            self._task_id = self._progress.add_task("Scan", total=samples_total)

        assert self._task_id is not None
        # cap displayed completed at total — eval_set retries can
        # re-execute samples, producing more `push_results` calls than
        # the initial estimate; clamping keeps the bar from rendering
        # past 100%
        completed = min(samples_completed, samples_total)
        self._progress.update(
            self._task_id,
            total=samples_total,
            completed=completed,
        )
        return self._progress
