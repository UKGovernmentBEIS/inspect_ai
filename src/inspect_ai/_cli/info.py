import click

from inspect_ai._util.constants import PKG_PATH
from inspect_ai.log import read_eval_log


@click.group("info")
def info_command() -> None:
    """Read configuration and log info."""
    return None


@info_command.command("log-file")
@click.argument("path")
@click.option(
    "--header-only",
    type=bool,
    is_flag=True,
    default=False,
    help="Read and print only the header of the log file (i.e. no samples).",
)
def log(path: str, header_only: bool) -> None:
    """Print log file contents."""
    log = read_eval_log(path, header_only=header_only)
    print(log.model_dump_json(indent=2))


@info_command.command("log-schema")
def log_schema() -> None:
    """Print JSON schema for log files."""
    print(view_resource("log-schema.json"))


@info_command.command("log-types")
def log_types() -> None:
    """Print TS declarations for log files."""
    print(view_resource("log.d.ts"))


def view_resource(file: str) -> str:
    resource = PKG_PATH / "src" / "inspect_ai" / "_view" / "www" / file
    with open(resource, "r", encoding="utf-8") as f:
        return f.read()
