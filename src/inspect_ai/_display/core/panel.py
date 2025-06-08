from typing import Tuple

import rich
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from inspect_ai._util.constants import CONSOLE_DISPLAY_WIDTH
from inspect_ai._util.path import cwd_relative_path
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai.util._display import display_type_plain

from .display import TaskProfile
from .rich import is_vscode_notebook, rich_theme


def task_panel(
    profile: TaskProfile,
    show_model: bool,
    body: RenderableType,
    subtitle: RenderableType
    | str
    | Tuple[RenderableType | str, RenderableType | str]
    | None,
    footer: RenderableType | tuple[RenderableType, RenderableType] | None,
    log_location: str | None,
) -> RenderableType:
    # dispatch to plain handler if we are in plain mode
    if display_type_plain():
        return task_panel_plain(
            profile, show_model, body, subtitle, footer, log_location
        )

    # rendering context
    theme = rich_theme()
    console = rich.get_console()
    width = CONSOLE_DISPLAY_WIDTH if is_vscode_notebook(console) else None
    jupyter = console.is_jupyter

    # root table
    table = Table.grid(expand=True)
    table.add_column()

    # setup table
    if subtitle is not None:
        subtitle_table = Table.grid(expand=True)
        subtitle_table.add_column()
        if isinstance(subtitle, tuple):
            subtitle_table.add_column(justify="right")
            subtitle_table.add_row(
                to_renderable(subtitle[0]), to_renderable(subtitle[1], style=theme.meta)
            )
        else:
            subtitle_table.add_row(to_renderable(subtitle))

        table.add_row(subtitle_table)

    # main progress and task info
    if body:
        table.add_row(body)

    # spacing if there is more content
    if footer or log_location:
        table.add_row()

    # footer if specified
    if footer:
        footer_table = Table.grid(expand=True)
        footer_table.add_column()
        if isinstance(footer, tuple):
            footer_table.add_column(justify="right")
            footer_table.add_row(footer[0], footer[1])
        else:
            footer_table.add_row(footer)
        table.add_row(footer_table)

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
        root.add_column(overflow="fold")
        root.add_row(table)
        root.add_row()
        root.add_row(
            f"[bold][{theme.light}]Log:[/{theme.light}][/bold] "
            + f"[{theme.link}]{log_location_relative}[/{theme.link}]"
        )
        root.add_row()

        panel = Panel(
            task_panel_title(profile, show_model),
            padding=(0, 0),
            width=width,
            height=3,
            expand=True,
        )
        return Group(panel, root)
    else:
        return Panel(
            root,
            title=task_panel_title(profile, show_model),
            title_align="left",
            width=width,
            expand=True,
        )


def task_panel_plain(
    profile: TaskProfile,
    show_model: bool,
    body: RenderableType,
    subtitle: RenderableType
    | str
    | Tuple[RenderableType | str, RenderableType | str]
    | None,
    footer: RenderableType | tuple[RenderableType, RenderableType] | None,
    log_location: str | None,
) -> RenderableType:
    # delimiter text
    delimeter = "---------------------------------------------------------"

    # root table for output
    table = Table.grid(expand=False)
    table.add_column()
    table.add_row(delimeter)

    # title and subtitle
    table.add_row(task_panel_title(profile, show_model))
    if isinstance(subtitle, tuple):
        subtitle = subtitle[0]
    table.add_row(subtitle)

    # task info
    if body:
        table.add_row(body)

    # footer
    if isinstance(footer, tuple):
        footer = footer[0]
    if footer:
        table.add_row(footer)

    # log location
    if log_location:
        # Print a cwd relative path
        try:
            log_location_relative = cwd_relative_path(log_location, walk_up=True)
        except ValueError:
            log_location_relative = log_location
        table.add_row(f"Log: {log_location_relative}")

    table.add_row(delimeter)
    table.add_row("")

    return table


def task_panel_title(profile: TaskProfile, show_model: bool) -> str:
    theme = rich_theme()
    return (
        f"[bold][{theme.meta}]{task_title(profile, show_model)}[/{theme.meta}][/bold]"
    )


def to_renderable(item: RenderableType | str, style: str = "") -> RenderableType:
    if isinstance(item, str):
        return Text.from_markup(item, style=style)
    else:
        return item


def tasks_title(completed: int, total: int) -> str:
    return f"{completed}/{total} tasks complete"


def task_title(profile: TaskProfile, show_model: bool) -> str:
    eval_epochs = profile.eval_config.epochs or 1
    epochs = f" x {profile.eval_config.epochs}" if eval_epochs > 1 else ""
    samples = f"{profile.samples // eval_epochs:,}{epochs} sample{'s' if profile.samples != 1 else ''}"
    title = f"{registry_unqualified_name(profile.name)} ({samples})"
    if show_model:
        title = f"{title}: {profile.model}"
    return title


def task_targets(profile: TaskProfile) -> str:
    return f"dataset: {profile.dataset}"
