from contextvars import ContextVar
from logging import getLogger
from typing import Any, NoReturn, cast

from shortuuid import uuid

from .environment import (
    SampleCleanup,
    SampleInit,
    SandboxConnection,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from .registry import registry_find_sandboxenv

logger = getLogger(__name__)


def sandbox(name: str | None = None) -> SandboxEnvironment:
    """Get the SandboxEnvironment for the current sample.

    Args:
      name (str | None): Optional sandbox environmnent name.

    Return:
      SandboxEnvironment instance.
    """
    # verify we have a context
    environments = sandbox_environments_context_var.get(None)
    if not environments:
        raise raise_no_sandbox()

    # For None, 'default', or a single environment only take the first environment
    if name is None or name == "default" or len(environments) == 1:
        return list(environments.values())[0]
    else:
        environment = environments.get(name, None)
        if not environment:
            raise ValueError(
                f"SandboxEnvironment '{name}' is not a recoginized environment name."
            )
        return environment


async def sandbox_with(file: str) -> SandboxEnvironment | None:
    """Get the SandboxEnvironment for the current sample that has the specified file.

    Args:
      file (str): Path to file to check for.

    Return:
      SandboxEnvironment instance or None if no sandboxes had the file.
    """
    # get environments and with mapping
    environments = sandbox_environments_context_var.get(None)
    if environments is None:
        raise_no_sandbox()
    environments_with = sandbox_with_environments_context_var.get(None)
    if environments_with is None:
        raise_no_sandbox()

    # if we've already disovered the sandbox for this file then return it
    environment = environments_with.get(file, None)
    if environment is not None:
        return environment

    # look in each sandbox
    for _, environment in environments.items():
        try:
            # can we read the file?
            await environment.read_file(file)

            # if so this is our environment, cache and return it
            environments_with[file] = environment
            return environment

        # allow exception types known to be raised from read_file
        except (
            FileNotFoundError,
            UnicodeDecodeError,
            PermissionError,
            IsADirectoryError,
        ):
            pass

    # not found
    return None


async def sandbox_connections() -> dict[str, SandboxConnection]:
    environments = sandbox_environments_context_var.get(None)
    if environments:
        connections: dict[str, SandboxConnection] = {}
        for name, environment in environments.items():
            try:
                connections[name] = await environment.connection()
            except (NotImplementedError, ConnectionError):
                pass
        return connections
    else:
        return {}


def raise_no_sandbox() -> NoReturn:
    raise RuntimeError(
        "No sandbox environment has been provided for the current sample or task. "
        + "Please specify a sandbox for the sample or a global default sandbox for the task"
    )


async def init_sandbox_environments_sample(
    type: str,
    task_name: str,
    config: SandboxEnvironmentConfigType | None,
    files: dict[str, bytes],
    setup: bytes | None,
    metadata: dict[str, Any],
) -> dict[str, SandboxEnvironment]:
    # get setup and cleanup functions
    sandboxenv_type = registry_find_sandboxenv(type)
    sample_init = cast(SampleInit, getattr(sandboxenv_type, "sample_init"))
    sample_cleanup = cast(SampleCleanup, getattr(sandboxenv_type, "sample_cleanup"))

    # create environments
    environments = await sample_init(task_name, config, metadata)

    # verify that there is at least one environment and a 'default' env
    validate_sandbox_environments(sandboxenv_type, environments)

    try:
        # copy files into environments
        await copy_sandbox_environment_files(files, environments)

        # run setup script
        if setup:
            await setup_sandbox_environment(setup, environments)

        # set context
        sandbox_environments_context_var.set(environments)
        sandbox_with_environments_context_var.set({})

        # return environments
        return environments

    except Exception as ex:
        await sample_cleanup(task_name, config, environments, True)
        raise ex


async def cleanup_sandbox_environments_sample(
    type: str,
    task_name: str,
    config: SandboxEnvironmentConfigType | None,
    environments: dict[str, SandboxEnvironment],
    interrupted: bool,
) -> None:
    sandboxenv_type = registry_find_sandboxenv(type)
    sample_cleanup = cast(SampleCleanup, getattr(sandboxenv_type, "sample_cleanup"))
    await sample_cleanup(task_name, config, environments, interrupted)


async def copy_sandbox_environment_files(
    files: dict[str, bytes], environments: dict[str, SandboxEnvironment]
) -> None:
    default_environment = default_sandbox_environment(environments)
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


async def setup_sandbox_environment(
    setup: bytes, environments: dict[str, SandboxEnvironment]
) -> None:
    # get default sandboxenv
    env = default_sandbox_environment(environments)

    # copy to container
    setup_file = f"/tmp/{uuid()}"
    await env.write_file(setup_file, setup)

    # chmod, execute, and remove
    async def exec(cmd: list[str]) -> None:
        result = await env.exec(cmd)

        if not result.success:
            raise RuntimeError(
                f"Failed to execute setup script for sample: {result.stderr}"
            )

    await exec(["chmod", "+x", setup_file])
    await exec(["env", setup_file])
    await exec(["rm", setup_file])


def default_sandbox_environment(
    environments: dict[str, SandboxEnvironment],
) -> SandboxEnvironment:
    return list(environments.values())[0]


def validate_sandbox_environments(
    type: type[SandboxEnvironment], environments: dict[str, SandboxEnvironment]
) -> None:
    if len(environments) == 0:
        raise ValueError(
            "No environments returned from sample_init() method "
            + f"of '{type.__name__}'. Did you provide an implementation "
            + "of the sample_init() class method? "
        )


sandbox_environments_context_var = ContextVar[dict[str, SandboxEnvironment]](
    "sandbox_environments"
)

sandbox_with_environments_context_var = ContextVar[dict[str, SandboxEnvironment]](
    "sandbox_with_environments"
)
