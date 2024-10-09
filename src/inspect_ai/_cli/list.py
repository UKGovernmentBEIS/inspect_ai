import os
from json import dumps
from typing import Literal
from urllib.parse import urlparse

import click
from fsspec.core import split_protocol  # type: ignore
from pydantic_core import to_jsonable_python
from typing_extensions import Unpack

from inspect_ai._cli.common import CommonOptions, common_options, resolve_common_options
from inspect_ai._cli.util import parse_cli_args
from inspect_ai._eval.list import list_tasks
from inspect_ai._eval.task import TaskInfo
from inspect_ai.log import list_eval_logs


@click.group("list")
def list_command() -> None:
    """List tasks or eval logs."""
    return None


@list_command.command()
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
    resolve_common_options(kwargs)

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


@list_command.command()
@click.option(
    "--status",
    type=click.Choice(["started", "success", "error"], case_sensitive=False),
    help="List only log files with the indicated status.",
)
@click.option(
    "--absolute",
    type=bool,
    is_flag=True,
    default=False,
    help="List absolute paths to log files (defaults to relative to the cwd).",
)
@click.option(
    "--json",
    type=bool,
    is_flag=True,
    default=False,
    help="Output listing as JSON",
)
@click.option(
    "--no-recursive",
    type=bool,
    is_flag=True,
    help="List log files recursively (defaults to True).",
)
@common_options
def logs(
    status: Literal["started", "success", "error"] | None,
    absolute: bool,
    json: bool,
    no_recursive: bool | None,
    **kwargs: Unpack[CommonOptions],
) -> None:
    """List log files in log directory."""
    (log_dir, _, _) = resolve_common_options(kwargs)

    # list the logs
    logs = list_eval_logs(
        log_dir=log_dir,
        filter=(lambda log: log.status == status) if status else None,
        recursive=no_recursive is not True,
    )

    # convert file names
    for log in logs:
        if urlparse(log.name).scheme == "file":
            _, path = split_protocol(log.name)
            log.name = path
            if not absolute:
                log.name = os.path.relpath(log.name, os.path.curdir)

    if json:
        logs_dicts = [log.model_dump() for log in logs]
        print(dumps(logs_dicts, indent=2))

    else:
        for log in logs:
            print(log.name)
