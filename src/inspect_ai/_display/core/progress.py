from typing import Callable

import rich
from rich.progress import (
    BarColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.progress import Progress as RProgress
from rich.text import Text
from typing_extensions import override

from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai.model._model import ModelName

from .display import Progress, TaskCancelled, TaskError, TaskProfile, TaskResult
from .rich import is_vscode_notebook, rich_theme

# Note that use of rich progress seems to result in an extra
# empty cell after execution, see: https://github.com/Textualize/rich/issues/3274

PROGRESS_TOTAL = 102


class RichProgress(Progress):
    def __init__(
        self,
        total: int,
        progress: RProgress,
        description: str = "",
        model: str = "",
        status: Callable[[], str] | None = None,
        on_update: Callable[[], None] | None = None,
        count: str = "",
        score: str = "",
    ) -> None:
        self.total = total
        self.progress = progress
        self.status = status if status else lambda: ""
        self.on_update = on_update
        self.task_id = progress.add_task(
            description,
            total=PROGRESS_TOTAL,
            model=model,
            status=self.status(),
            count=count,
            score=score,
        )

    @override
    def update(self, n: int = 1) -> None:
        advance = (float(n) / float(self.total)) * 100
        self.progress.update(
            task_id=self.task_id, advance=advance, refresh=True, status=self.status()
        )
        if self.on_update:
            self.on_update()

    @override
    def complete(self) -> None:
        self.progress.update(
            task_id=self.task_id, completed=PROGRESS_TOTAL, status=self.status()
        )

    def update_count(self, complete: int, total: int) -> None:
        self.progress.update(
            task_id=self.task_id, count=progress_count(complete, total), refresh=True
        )
        if self.on_update:
            self.on_update()

    def update_score(self, score: str) -> None:
        self.progress.update(task_id=self.task_id, score=score)


def rich_progress() -> RProgress:
    console = rich.get_console()
    return RProgress(
        TextColumn("{task.fields[status]}"),
        TextColumn("{task.description}"),
        TextColumn("{task.fields[model]}"),
        BarColumn(bar_width=40 if is_vscode_notebook(console) else None),
        TaskProgressColumn(),
        TextColumn("{task.fields[count]}"),
        TextColumn("{task.fields[score]}"),
        TimeElapsedColumn(),
        transient=True,
        console=console,
        expand=True,
    )


MAX_MODEL_NAME_WIDTH = 25
MAX_DESCRIPTION_WIDTH = 25


def progress_model_name(
    model_name: ModelName, max_width: int = MAX_MODEL_NAME_WIDTH, pad: bool = False
) -> Text:
    model = Text(str(model_name))
    model.truncate(max_width, overflow="ellipsis", pad=pad)
    return model


def progress_description(
    profile: TaskProfile, max_width: int = MAX_DESCRIPTION_WIDTH, pad: bool = False
) -> Text:
    description = Text(registry_unqualified_name(profile.name))
    description.truncate(max_width, overflow="ellipsis", pad=pad)
    return description


def progress_status_icon(result: TaskResult | None) -> str:
    theme = rich_theme()
    if result:
        if isinstance(result, TaskError):
            return f"[{theme.error}]✗[{theme.error}]"
        elif isinstance(result, TaskCancelled):
            return f"[{theme.error}]✗[{theme.error}]"
        else:
            return f"[{theme.success}]✔[{theme.success}]"
    else:
        return f"[{theme.meta}]⠿[{theme.meta}]"


def progress_time(time: float) -> str:
    minutes, seconds = divmod(time, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:2.0f}:{minutes:02.0f}:{seconds:02.0f}"


def progress_count(complete: int, total: int, width: int | None = None) -> str:
    # Pad the display to keep it stable as the
    # complete metrics
    total_str = f"{total:,}"
    complete_str = f"{complete:,}"
    padding = max(0, len(total_str) - len(complete_str))
    padded = " " * padding + f"[{complete_str}/{total_str}]"

    # If a width has ben specified, pad up to this width as well
    if width is not None:
        padded = padded.rjust(width)
    return padded
