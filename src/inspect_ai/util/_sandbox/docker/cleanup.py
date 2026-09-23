from contextvars import ContextVar
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path
from typing import Awaitable, Callable

import anyio
from rich import box, print
from rich.panel import Panel
from rich.table import Table

from inspect_ai._util._async import coro_print_exceptions
from inspect_ai._util.trace import trace_message
from inspect_ai.util._anyio import safe_current_task_id

from ..lifecycle import sandbox_lifecycle_state
from .compose import compose_down, compose_ls, compose_ps
from .config import auto_compose_dir, is_auto_compose_file, safe_cleanup_auto_compose
from .util import TRACE_DOCKER, ComposeProject, is_inspect_project

logger = getLogger(__name__)


@dataclass
class DockerCleanupState:
    """The Docker resources one eval batch has started and must clean up.

    Lives on the batch's sandbox lifecycle scope (``_sandbox/lifecycle.py``),
    so every task of the batch — the samples, and a ``SampleSource`` feeder
    that initializes a config late — registers with and reads the same object.
    """

    running_projects: list[ComposeProject] = field(default_factory=list)
    """Projects brought up by ``sample_init`` and not yet brought down."""

    auto_compose_files: set[str] = field(default_factory=set)
    """Generated compose files (startup and per-sample) to remove at shutdown."""

    closed: bool = False
    """``project_cleanup_shutdown`` has run: this lifecycle is finished."""

    owner: int | None = None
    """For a registry bound outside a scope, the id of the task that bound it."""


def cleanup_state() -> DockerCleanupState:
    """The cleanup registry of the enclosing sandbox lifecycle scope.

    Outside any scope — the provider driven directly, without a
    ``SandboxManager`` — the registry bound to the current context (see
    ``project_cleanup_startup``), binding one on first use if ``task_init``
    never ran here.
    """
    scope = sandbox_lifecycle_state()
    if scope is not None:
        return scope.get(DockerCleanupState)
    state = _ownerless_state.get()
    if state is None:
        state = _bind_ownerless_state()
    return state


def _bind_ownerless_state() -> DockerCleanupState:
    state = DockerCleanupState(owner=safe_current_task_id())
    _ownerless_state.set(state)
    return state


def project_cleanup_startup() -> None:
    """Bind the cleanup registry in the caller's context before samples start.

    Inside a scope the registry is the scope's: this only ensures it exists
    where child tasks will inherit it, and never resets it, so a late
    ``task_init`` (another config, added mid-run) keeps every resource the
    batch has already registered.

    Outside any scope a registry belongs to the task whose ``task_init`` bound
    it, for one lifecycle: a ``task_init`` in another task (a child that
    inherited the binding), or after the bound registry's ``task_cleanup`` has
    run, binds its own, so concurrent or successive direct-provider
    lifecycles never share cleanup state. Reads (``sample_init``,
    ``task_cleanup``) use whatever registry the context holds, so a lifecycle
    may still spread over a task and its children.
    """
    if sandbox_lifecycle_state() is not None:
        cleanup_state()
        return
    state = _ownerless_state.get()
    if state is None or state.closed or state.owner != safe_current_task_id():
        _bind_ownerless_state()


def _cleanup_orphaned_auto_compose_files(running_project_names: set[str]) -> None:
    """Remove auto-compose files that no longer have running Docker projects.

    Args:
        running_project_names: Set of currently running inspect project names.

    This handles cleanup for files left behind by crashed processes.
    """
    compose_dir = auto_compose_dir()

    # Remove files for projects no longer running
    for file in compose_dir.iterdir():
        if file.suffix == ".yaml" and file.stem not in running_project_names:
            try:
                file.unlink()
            except Exception as ex:
                trace_message(
                    logger,
                    TRACE_DOCKER,
                    f"Failed to remove orphaned compose file {file}: {ex}",
                )


def project_startup(project: ComposeProject) -> None:
    # track running projects
    cleanup_state().running_projects.append(project)

    # track auto compose we need to cleanup
    project_record_auto_compose(project)


def project_record_auto_compose(project: ComposeProject) -> bool:
    """Register a project's generated compose file for removal at shutdown.

    Returns whether this call registered it: ``False`` for an explicit compose
    file, and for a generated file already registered by an earlier
    initialization or a live sample (a legacy ``.compose.yaml``, or a path
    in the auto-compose directory reused by another configuration).
    """
    if project.config and is_auto_compose_file(project.config):
        auto_compose_files = cleanup_state().auto_compose_files
        if project.config not in auto_compose_files:
            auto_compose_files.add(project.config)
            return True
    return False


def project_discard_auto_compose(project: ComposeProject) -> None:
    """Remove a project's generated compose file and forget it.

    For a ``task_init`` that fails after generating its startup config, when
    that init alone registered the file (``project_record_auto_compose``
    returned ``True``): only that file goes, so the batch's live samples and
    its other configs are untouched and its final cleanup still runs. A file a
    running project uses is kept regardless: its ``compose`` commands still
    name it.
    """
    if project.config and is_auto_compose_file(project.config):
        state = cleanup_state()
        if any(running.config == project.config for running in state.running_projects):
            return
        state.auto_compose_files.discard(project.config)
        safe_cleanup_auto_compose(project.config)


async def project_cleanup(project: ComposeProject, quiet: bool = True) -> None:
    # bring down services
    await compose_down(project=project, quiet=quiet)

    # remove the project from the list of running projects
    running_projects = cleanup_state().running_projects
    if project in running_projects:
        running_projects.remove(project)


async def project_cleanup_shutdown(cleanup: bool) -> None:
    """Bring down (or report) every registered project and release the registry.

    The batch's ``SandboxManager`` calls this once per Docker config it
    started, at the end of the batch. Every entry processed is released, so
    the repeat calls do nothing and no entry carries into a later batch.
    """
    state = cleanup_state()

    # get projects that still need shutting down
    shutdown_projects = list(state.running_projects)

    # full cleanup if requested
    if len(shutdown_projects) > 0:
        if cleanup:
            await cleanup_projects(shutdown_projects)

        else:
            print("")
            table = Table(
                title="Docker Sandbox Environments (not yet cleaned up):",
                box=box.SQUARE_DOUBLE_HEAD,
                show_lines=True,
                title_style="bold",
                title_justify="left",
            )
            table.add_column("Sample ID")
            table.add_column("Epoch")
            table.add_column("Container(s)", no_wrap=True)
            for project in shutdown_projects:
                containers = await compose_ps(project, all=True)
                table.add_row(
                    str(project.sample_id) if project.sample_id is not None else "",
                    str(project.epoch if project.epoch is not None else ""),
                    "\n".join(container["Name"] for container in containers),
                )
            print(table)
            print(
                "\n"
                "Cleanup all containers  : [blue]inspect sandbox cleanup docker[/blue]\n"
                "Cleanup single container: [blue]inspect sandbox cleanup docker <container-id>[/blue]",
                "\n",
            )

    # release the processed projects (brought down, or handed to the user)
    for project in shutdown_projects:
        if project in state.running_projects:
            state.running_projects.remove(project)

    # remove auto-compose files
    for file in list(state.auto_compose_files):
        safe_cleanup_auto_compose(file)
        state.auto_compose_files.discard(file)

    state.closed = True


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
    async with anyio.create_task_group() as tg:
        for project in projects:
            tg.start_soon(
                coro_print_exceptions,
                "cleaning up Docker environment",
                cleanup_fn,
                project,
                False,
            )


async def cli_cleanup(project_name: str | None) -> None:
    # enumerate all inspect projects
    projects = await compose_ls()

    # get set of running project names for orphan cleanup
    running_names = {p.Name for p in projects if is_inspect_project(p.Name)}

    # filter by project name
    if project_name:
        projects = list(filter(lambda p: p.Name == project_name, projects))

    # if the config files are missing then blank them out so we get auto-compose
    for project in projects:
        if project.ConfigFiles and not Path(project.ConfigFiles).exists():
            project.ConfigFiles = None

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
        for compose_project in compose_projects:
            safe_cleanup_auto_compose(compose_project.config)

    # clean up orphaned auto-compose files from crashed processes
    _cleanup_orphaned_auto_compose_files(running_names)


# the registry for provider use outside any sandbox lifecycle scope; bound by
# the task running task_init, per lifecycle (never a shared mutable default,
# which would carry one run's projects into the next)
_ownerless_state: ContextVar[DockerCleanupState | None] = ContextVar(
    "docker_cleanup_state", default=None
)
