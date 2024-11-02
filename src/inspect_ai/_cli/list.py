from json import dumps
from typing import Literal

import click
from pydantic_core import to_jsonable_python
from typing_extensions import Unpack

from inspect_ai._cli.common import CommonOptions, common_options, process_common_options
from inspect_ai._cli.log import list_logs_options, log_list
from inspect_ai._cli.util import parse_cli_args
from inspect_ai._eval.list import list_tasks
from inspect_ai._eval.task import TaskInfo


@click.group("list")
def list_command() -> None:
    """List tasks or eval logs."""
    return None


@list_command.command("tasks")
@click.option(
    "-F",
    multiple=True,
    type=str,
    help="One or more boolean task filters (e.g. -F light=true or -F draft~=false)",
)
@click.option(
    "--absolute",
    type=bool,
    is_flag=True,
    default=False,
    help="List absolute paths to task scripts (defaults to relative to the cwd).",
)
@click.option(
    "--json",
    type=bool,
    is_flag=True,
    default=False,
    help="Output listing as JSON",
)
@click.argument("paths", nargs=-1)
@common_options
def tasks(
    paths: tuple[str] | None,
    f: tuple[str] | None,
    absolute: bool,
    json: bool,
    **kwargs: Unpack[CommonOptions],
) -> None:
    """List tasks in given directories."""
    # resolve common options
    process_common_options(kwargs)

    # parse filter expressions and build a filter from it
    filters = parse_cli_args(f)

    def task_filter(task: TaskInfo) -> bool:
        for name, value in filters.items():
            if name.endswith("~"):
                name = name[:-1]
                include = task.attribs.get(name, None) != value
            else:
                include = task.attribs.get(name, None) == value
            if not include:
                return False
        return True

    # list tasks
    tasks = list_tasks(
        globs=list(paths) if paths else [], absolute=absolute, filter=task_filter
    )

    # print as JSON or plain text
    if json:
        print(dumps(to_jsonable_python(tasks, exclude_none=True), indent=2))
    else:
        print("\n".join([f"{task.file}@{task.name}" for task in tasks]))


@list_command.command("logs", hidden=True)
@list_logs_options
def list_logs_command(
    status: Literal["started", "success", "cancelled", "error"] | None,
    absolute: bool,
    json: bool,
    no_recursive: bool | None,
    **common: Unpack[CommonOptions],
) -> None:
    log_list(status, absolute, json, no_recursive, **common)
