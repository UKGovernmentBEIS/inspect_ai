from contextvars import ContextVar
from logging import getLogger
from typing import Any, Awaitable, Callable, cast

from .environment import (
    SampleCleanup,
    SampleInit,
    TaskCleanup,
    TaskInit,
    ToolEnvironment,
)
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
    environments = tool_environments_context_var.get(None)
    if not environments:
        raise RuntimeError(
            "No tool environment has been provided for the current task. "
            + "Please specify one using either the tool_environment task/eval "
            + "option, or the --toolenv CLI option."
        )

    # short circuit for 1 environment (allows single environment to not sweat 'default')
    if len(environments) == 1:
        return list(environments.values())[0]

    # lookup the environment by name
    environment = environments.get(name, None)
    if not environment:
        raise ValueError(
            f"ToolEnvironment '{name}' is not a recoginized environment name."
        )

    return environment


async def startup_tool_environments(
    task_name: str, tool_environment: tuple[str, str | None], cleanup: bool
) -> Callable[[], Awaitable[None]]:
    # find type
    toolenv_type = registry_find_toolenv(tool_environment[0])

    # run startup
    task_init = cast(TaskInit, getattr(toolenv_type, "task_init"))
    await task_init(task_name, tool_environment[1])

    # return shutdown method
    task_cleanup = cast(TaskCleanup, getattr(toolenv_type, "task_cleanup"))

    async def shutdown() -> None:
        await task_cleanup(task_name, tool_environment[1], cleanup)

    return shutdown


async def init_tool_environments_sample(
    type: str,
    task_name: str,
    config: str | None,
    files: dict[str, bytes],
    metadata: dict[str, Any],
) -> dict[str, ToolEnvironment]:
    # get setup and cleanup functions
    toolenv_type = registry_find_toolenv(type)
    sample_init = cast(SampleInit, getattr(toolenv_type, "sample_init"))
    sample_cleanup = cast(SampleCleanup, getattr(toolenv_type, "sample_cleanup"))

    # create environments
    environments = await sample_init(task_name, config, metadata)

    # verify that there is at least one environment and a 'default' env
    validate_tool_environments(toolenv_type, environments)

    try:
        # copy files into environments
        await copy_tool_environment_files(files, environments)

        # set context
        tool_environments_context_var.set(environments)

        # return environments
        return environments

    except Exception as ex:
        await sample_cleanup(task_name, config, environments, True)
        raise ex


async def cleanup_tool_environments_sample(
    type: str,
    task_name: str,
    config: str | None,
    environments: dict[str, ToolEnvironment],
    interrupted: bool,
) -> None:
    toolenv_type = registry_find_toolenv(type)
    sample_cleanup = cast(SampleCleanup, getattr(toolenv_type, "sample_cleanup"))
    await sample_cleanup(task_name, config, environments, interrupted)


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


def validate_tool_environments(
    type: type[ToolEnvironment], environments: dict[str, ToolEnvironment]
) -> None:
    if len(environments) == 0:
        raise ValueError(
            "No environments returned from sample_init() method "
            + f"of '{type.__name__}'. Did you provide an implementation "
            + "of the sample_init() class method? "
        )

    if environments.get("default", None) is None:
        raise RuntimeError(f"No 'default' service provided for {type.__name__}")


tool_environments_context_var = ContextVar[dict[str, ToolEnvironment]](
    "tool_environments"
)
