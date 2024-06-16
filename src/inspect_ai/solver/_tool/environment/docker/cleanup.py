import asyncio
from contextvars import ContextVar

from rich import print
from rich.panel import Panel

from inspect_ai._util.error import exception_message

from .compose import compose_down
from .config import auto_config_cleanup
from .util import ComposeProject


def project_cleanup_startup() -> None:
    _running_projects.set([])


def project_startup(project: ComposeProject) -> None:
    running_projects().append(project)


async def project_cleanup(project: ComposeProject, quiet: bool = True) -> None:
    # bring down services
    await compose_down(project=project, quiet=quiet)

    # remove the project from the list of running projects
    running_projects().remove(project)


async def project_cleanup_shutdown() -> None:
    # get projects that still need shutting down
    shutdown_projects = running_projects().copy()

    if len(shutdown_projects) > 0:
        # urge the user to let this operation complete
        print(
            Panel(
                "[bold][blue]Cleaning up Docker containers "
                + "(please do not interrupt this operation!):[/blue][/bold]",
            )
        )

        # cleanup all of the projects in parallel
        tasks = [project_cleanup(project, False) for project in shutdown_projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # report errors
        for result in results:
            if result is not None:
                print(
                    f"Error cleaning up compose containers: {exception_message(result)}"
                )

    # cleanup auto config
    auto_config_cleanup()


def running_projects() -> list[ComposeProject]:
    return _running_projects.get()


_running_projects: ContextVar[list[ComposeProject]] = ContextVar(
    "docker_running_projects"
)
