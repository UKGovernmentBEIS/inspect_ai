import rich
from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from inspect_ai._util.constants import CONSOLE_DISPLAY_WIDTH
from inspect_ai._util.path import cwd_relative_path
from inspect_ai._util.registry import registry_unqualified_name

from .display import TaskProfile
from .rich import is_vscode_notebook, rich_theme


def task_panel(
    profile: TaskProfile,
    show_model: bool,
    body: RenderableType,
    footer: RenderableType | tuple[RenderableType, RenderableType] | None,
    log_location: str | None,
) -> Panel:
    # rendering context
    theme = rich_theme()
    console = rich.get_console()
    width = CONSOLE_DISPLAY_WIDTH if is_vscode_notebook(console) else None
    jupyter = console.is_jupyter

    # setup table
    table = Table.grid(expand=True)
    table.add_column()
    table.add_column(justify="right")

    # main progress and task info
    targets = Text.from_markup(task_targets(profile), style=theme.meta)
    table.add_row(body, targets)

    # footer if specified
    if footer:
        table.add_row()
        if isinstance(footer, tuple):
            table.add_row(footer[0], footer[1])
        else:
            table.add_row(footer)

    # enclose in outer table for log link footer
    root = table
    if log_location:
        # if we are in jupyter then use a real hyperlink
        if jupyter:
            log_location = f"[link={log_location}]{log_location}[/link]"

        # Print a cwd relative path
        try:
            log_location_relative = cwd_relative_path(log_location, walk_up=True)
        except ValueError:
            log_location_relative = log_location

        root = Table.grid(expand=True)
        root.add_column()
        root.add_row(table)
        root.add_row()
        root.add_row(
            f"[bold][{theme.light}]Log:[/{theme.light}][/bold] "
            + f"[{theme.link}]{log_location_relative}[/{theme.link}]"
        )

    # create panel w/ title
    panel = Panel(
        root,
        title=f"[bold][{theme.meta}]{task_title(profile, show_model)}[/{theme.meta}][/bold]",
        title_align="left",
        width=width,
        expand=True,
    )
    return panel


def tasks_title(completed: int, total: int) -> str:
    return f"{completed}/{total} tasks complete"


def task_title(profile: TaskProfile, show_model: bool) -> str:
    eval_epochs = profile.eval_config.epochs or 1
    epochs = f" x {profile.eval_config.epochs}" if eval_epochs > 1 else ""
    samples = f"{profile.samples//eval_epochs:,}{epochs} sample{'s' if profile.samples > 1 else ''}"
    title = f"{registry_unqualified_name(profile.name)} ({samples})"
    if show_model:
        title = f"{title}: {profile.model}"
    return title


def task_targets(profile: TaskProfile) -> str:
    return f"dataset: {profile.dataset}"
