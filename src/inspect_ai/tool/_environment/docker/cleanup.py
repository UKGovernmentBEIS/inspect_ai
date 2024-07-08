import asyncio
from contextvars import ContextVar
from typing import Awaitable, Callable, Set

from rich import box, print
from rich.panel import Panel
from rich.table import Table

from inspect_ai._util.error import exception_message

from .compose import compose_down, compose_ls, compose_ps
from .config import is_auto_compose_file, safe_cleanup_auto_compose
from .util import ComposeProject


def project_cleanup_startup() -> None:
    _running_projects.set([])
    _auto_compose_files.set(set())


def project_startup(project: ComposeProject) -> None:
    # track running projects
    running_projects().append(project)

    # track auto compose we need to cleanup
    if project.config and is_auto_compose_file(project.config):
        auto_compose_files().add(project.config)


async def project_cleanup(project: ComposeProject, quiet: bool = True) -> None:
    # bring down services
    await compose_down(project=project, quiet=quiet)

    # remove the project from the list of running projects
    running_projects().remove(project)


async def project_cleanup_shutdown(cleanup: bool) -> None:
    # get projects that still need shutting down
    shutdown_projects = running_projects().copy()

    # full cleanup if requested
    if len(shutdown_projects) > 0:
        if cleanup:
            await cleanup_projects(shutdown_projects)

        else:
            print("")
            table = Table(
                title="Docker Tool Environments (not yet cleaned up):",
                box=box.SQUARE_DOUBLE_HEAD,
                show_lines=True,
                title_style="bold",
                title_justify="left",
            )
            table.add_column("Container(s)", no_wrap=True)
            table.add_column("Cleanup")
            for project in shutdown_projects:
                containers = await compose_ps(project, all=True)
                table.add_row(
                    "\n".join(container["Name"] for container in containers),
                    f"[blue]inspect toolenv cleanup docker {project.name}[/blue]",
                )
            print(table)
            print(
                "\nCleanup all environments with: [blue]inspect toolenv cleanup docker[/blue]\n"
            )

    # remove auto-compose files
    for file in auto_compose_files().copy():
        safe_cleanup_auto_compose(file)


async def cleanup_projects(
    projects: list[ComposeProject],
    cleanup_fn: Callable[[ComposeProject, bool], Awaitable[None]] = project_cleanup,
) -> None:
    # urge the user to let this operation complete
    print(
        Panel(
            "[bold][blue]Cleaning up Docker environments "
            + "(please do not interrupt this operation!):[/blue][/bold]",
        )
    )

    # cleanup all of the projects in parallel
    tasks = [cleanup_fn(project, False) for project in projects]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # report errors
    for result in results:
        if result is not None:
            print(f"Error cleaning up Docker environment: {exception_message(result)}")


async def cli_cleanup(project_name: str | None) -> None:
    # enumerate all inspect projects
    projects = await compose_ls()

    # filter by project name
    if project_name:
        projects = list(filter(lambda p: p.Name == project_name, projects))

    # clean them up
    if len(projects) > 0:
        # create compose projects
        compose_projects = [
            await ComposeProject.create(name=project.Name, config=project.ConfigFiles)
            for project in projects
        ]

        # do the cleanup
        await cleanup_projects(compose_projects, cleanup_fn=compose_down)

        # remove auto compose files
        for project in projects:
            safe_cleanup_auto_compose(project.ConfigFiles)


def running_projects() -> list[ComposeProject]:
    return _running_projects.get()


def auto_compose_files() -> Set[str]:
    return _auto_compose_files.get()


_running_projects: ContextVar[list[ComposeProject]] = ContextVar(
    "docker_running_projects"
)

_auto_compose_files: ContextVar[Set[str]] = ContextVar("docker_auto_compose_files")
