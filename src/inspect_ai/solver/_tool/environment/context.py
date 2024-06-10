from contextvars import ContextVar
from logging import getLogger
from typing import Any

from .environment import ToolEnvironment, ToolEnvironments
from .registry import registry_find_toolenv

logger = getLogger(__name__)


def tool_environment(name: str = "default") -> ToolEnvironment:
    """Get the ToolEnvironment for the current sample.

    Args:
       name (str | None): Optional tool environmnent name.

    Return:
       ToolEnvironment instance.
    """
    # verify we have a context
    context = tool_environments_context_var.get(None)
    if not context:
        raise RuntimeError(
            "No tool environment has been provided for the current task. "
            + "Please specify one using either the tool_environment task/eval "
            + "option, or the --tool-environment CLI option."
        )

    # short circuit for 1 environment (allows single environment to not sweat 'default')
    if len(context.environments) == 1:
        return list(context.environments.values())[0]

    # lookup the environment by name
    environment = context.environments.get(name, None)
    if not environment:
        raise ValueError(
            f"ToolEnvironment '{name}' is not a recoginized environment name."
        )
    return environment


async def startup_tool_environments(
    task_name: str, tool_environment: tuple[str, str | None]
) -> None:
    toolenv_type = registry_find_toolenv(tool_environment[0])
    toolenv_startup = getattr(toolenv_type, "startup")
    await toolenv_startup(task_name, tool_environment[1])


async def init_tool_environments_context(
    type: str,
    task_name: str,
    config: str | None,
    files: dict[str, bytes],
    metadata: dict[str, Any],
) -> None:
    # create environments based on type
    toolenv_type = registry_find_toolenv(type)
    toolenv_setup = getattr(toolenv_type, "setup")
    context: ToolEnvironments = await toolenv_setup(task_name, config, metadata)

    try:
        # copy files into environments
        await copy_tool_environment_files(files, context.environments)

        # set context
        tool_environments_context_var.set(context)
    except Exception as ex:
        if context.cleanup:
            await context.cleanup(True)
        raise ex


async def copy_tool_environment_files(
    files: dict[str, bytes], environments: dict[str, ToolEnvironment]
) -> None:
    default_environment = (
        list(environments.values())[0]
        if len(environments) == 1
        else environments["default"]
    )
    for file, contents in files.items():
        # does it have an environment prefix? if so target that env
        parts = file.split(":", maxsplit=1)
        if len(parts) > 1:
            envname = parts[0]
            file = parts[1]
            target_env = environments.get(envname, None)
            if not target_env:
                raise RuntimeError(
                    f"Environment referenced in sample file not found: '{envname}:{file}'"
                )
        else:
            target_env = default_environment

        await target_env.write_file(file, contents)


async def cleanup_tool_environments_context(cancelled: bool) -> None:
    context = tool_environments_context_var.get(None)
    if context and context.cleanup:
        try:
            await context.cleanup(cancelled)
        except Exception:
            logger.warning("Error cleaning up tool environments", exc_info=True)


tool_environments_context_var = ContextVar[ToolEnvironments]("tool_environments")
