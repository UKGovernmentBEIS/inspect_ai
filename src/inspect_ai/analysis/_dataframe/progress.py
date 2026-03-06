from contextlib import contextmanager
from typing import Iterator, Protocol

from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)


class ImportProgress(Protocol):
    def update(self) -> None: ...
    def reset(self, description: str, completed: int, total: int) -> None: ...


class NoProgress(ImportProgress):
    def update(self) -> None:
        pass

    def reset(self, description: str, completed: int, total: int) -> None:
        pass


class RichImportProgress(ImportProgress):
    def __init__(self, progress: Progress, task_id: TaskID) -> None:
        self._progress = progress
        self._task_id = task_id

    def update(self) -> None:
        self._progress.update(self._task_id, advance=1)

    def reset(self, description: str, completed: int, total: int) -> None:
        self._progress.reset(
            self._task_id, description=description, completed=completed, total=total
        )


@contextmanager
def no_progress() -> Iterator[ImportProgress]:
    yield NoProgress()


@contextmanager
def import_progress(description: str, total: float | None) -> Iterator[ImportProgress]:
    with Progress(
        TextColumn("[progress.description]{task.description:<18}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        task_id = progress.add_task(description, total=total)
        yield RichImportProgress(progress, task_id)
