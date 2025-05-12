from contextlib import contextmanager
from typing import Iterator

from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)


@contextmanager
def import_progress(
    description: str, total: float | None
) -> Iterator[tuple[Progress, TaskID]]:
    with Progress(
        TextColumn("[progress.description]{task.description:<18}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        task_id = progress.add_task(description, total=total)
        yield progress, task_id
