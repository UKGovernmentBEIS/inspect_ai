from rich.progress import (
    ProgressColumn,
    Task,
)
from rich.text import Text

from inspect_ai.scanner._concurrency.common import WorkerMetrics


class UtilizationColumn(ProgressColumn):
    """Progress column showing worker utilization (active/max)."""

    def render(self, task: Task) -> Text:
        metrics: WorkerMetrics | None = task.fields.get("metrics")
        if metrics is None:
            return Text("0/0/0 (0)", style="cyan")
        return Text(
            f"{metrics.workers_scanning}/{metrics.workers_waiting}/{metrics.worker_count} ({metrics.buffered_jobs})",
            style="cyan",
        )
