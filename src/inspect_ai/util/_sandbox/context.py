from contextlib import contextmanager
from contextvars import ContextVar
from logging import getLogger
from typing import Any, Awaitable, Callable, Iterator, NamedTuple, NoReturn, cast

from shortuuid import uuid

from inspect_ai._util.constants import SANDBOX_SETUP_TIMEOUT
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy

from .environment import (
    SampleCleanup,
    SampleInit,
    SandboxConnection,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from .registry import registry_find_sandboxenv

logger = getLogger(__name__)

# Type definitions for sandbox injection
Detector = Callable[["SandboxEnvironment"], Awaitable[bool]]
Injector = Callable[["SandboxEnvironment"], Awaitable[None]]


class SandboxInjectable(NamedTuple):
    """A detector/injector pair for sandbox injection.

    Attributes:
        detector: Function that checks if injection is needed.
        injector: Function that performs the injection.
    """

    detector: Detector
    injector: Injector


def sandbox(name: str | None = None) -> SandboxEnvironment:
    """Get the SandboxEnvironment for the current sample.

    Args:
      name (str | None): Optional sandbox environment name.

    Return:
      SandboxEnvironment instance.

    Raises:
      ProcessLookupError: If there are no sandboxes available.
      ValueError: If an invalid sandbox name is specified.
    """
    # verify we have a context
    environments = sandbox_environments_context_var.get(None)
    if not environments:
        raise raise_no_sandbox()

    # For None, 'default', or a single environment only take the first environment
    if name is None or name == "default" or len(environments) == 1:
        return default_sandbox_environment(environments)
    else:
        environment = environments.get(name, None)
        if not environment:
            raise ValueError(
                f"SandboxEnvironment '{name}' is not a recognized environment name."
            )
        return environment


async def sandbox_with(
    file: str, on_path: bool = False, *, name: str | None = None
) -> SandboxEnvironment | None:
    """Get the SandboxEnvironment for the current sample that has the specified file.

    Args:
      file (str): Path to file to check for if on_path is False. If on_path is
        True, file should be a filename that exists on the system path.
      on_path (bool): If True, file is a filename to be verified using "which".
        If False, file is a path to be checked within the sandbox environments.
      name (str | None): Optional sandbox environment name.


    Return:
      SandboxEnvironment instance or None if none of the sandboxes (or the named
      sandbox) had the file.
    """
    # get environments and with mapping
    environments = sandbox_environments_context_var.get(None)
    if environments is None:
        raise_no_sandbox()
    environments_with = sandbox_with_environments_context_var.get(None)
    if environments_with is None:
        raise_no_sandbox()

    # if we've already discovered the sandbox for this file then return it
    environment_with_key = f"{name or ''}:{file}:{on_path}"
    environment = environments_with.get(environment_with_key, None)
    if environment is not None:
        return environment

    # look in each (or the named) sandbox
    detector = sandbox_file_detector(file, on_path)
    for environment in (
        environments.values()
        if name is None
        else [named_env]
        if (named_env := environments.get(name, None))
        else []
    ):
        # can we find the file on the path?
        if await detector(environment):
            # if so this is our environment, cache and return it
            environments_with[environment_with_key] = environment
            return environment

    # not found
    return None


async def _is_file_readable(environment: SandboxEnvironment, file: str) -> bool:
    try:
        # TODO: This is gross. We actually read the file contents just to see if
        # it's readable.
        await environment.read_file(file, False)
        return True
    # allow exception types known to be raised from read_file
    except (
        FileNotFoundError,
        UnicodeDecodeError,
        PermissionError,
        IsADirectoryError,
    ):
        return False


def sandbox_file_detector(file: str, on_path: bool = False) -> Detector:
    """Create a detector for use with sandbox_with_injection that checks a sandbox for file existence.

    Args:
        file: Path to file to check for if on_path is False. If on_path is
            True, file should be a filename that exists on the system path.
        on_path: If True, file is a filename to be verified using "which".
            If False, file is a path to be checked within the sandbox.

    Returns:
        Detector function that returns True if the file exists.
    """

    async def detect_on_path(sandbox: SandboxEnvironment) -> bool:
        return (await sandbox.exec(["which", file])).success

    async def detect_file(sandbox: SandboxEnvironment) -> bool:
        return await _is_file_readable(sandbox, file)

    return detect_on_path if on_path else detect_file


async def sandbox_with_injection(
    injectables: SandboxInjectable | list[SandboxInjectable],
    name: str | None = None,
) -> SandboxEnvironment:
    """Get a SandboxEnvironment that satisfies all the given injection requirements.

    Args:
        injectables: Single SandboxInjectable or list of SandboxInjectables.
            Each injectable is a (detector, injector) tuple.
        name: Optional sandbox environment name.

    Returns:
        SandboxEnvironment instance that satisfies all injection requirements.

    Raises:
        ProcessLookupError: If there are no sandboxes available.
        ValueError: If an invalid sandbox name is specified.
        RuntimeError: If injection fails.
    """
    if isinstance(injectables, tuple):
        injectables = [injectables]

    target_sandbox, needed_injections = (
        # Named sandbox: inject directly into the specified sandbox
        (sb := sandbox(name), await _get_needed_injections(sb, injectables))
        if name
        # Unnamed sandbox: find best candidate (fewest injections needed)
        else await _get_injection_target(injectables)
    )

    for detector, injector in needed_injections:
        await injector(target_sandbox)
        # Verify injection succeeded
        if not await detector(target_sandbox):
            raise RuntimeError(
                "Injection failed - detector still returns False after injection"
            )

    return target_sandbox


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
    raise ProcessLookupError(
        "No sandbox environment has been provided for the current sample or task. "
        + "Please specify a sandbox for the sample or a global default sandbox for the task"
    )


async def init_sandbox_environments_sample(
    sandboxenv_type: type[SandboxEnvironment],
    task_name: str,
    config: SandboxEnvironmentConfigType | None,
    files: dict[str, bytes],
    setup: bytes | None,
    metadata: dict[str, Any],
) -> dict[str, SandboxEnvironment]:
    # get setup and cleanup functions
    sample_init = cast(SampleInit, getattr(sandboxenv_type, "sample_init"))
    sample_cleanup = cast(SampleCleanup, getattr(sandboxenv_type, "sample_cleanup"))

    # create environments
    environments = await sample_init(task_name, config, metadata)

    # verify that there is at least one environment and a 'default' env
    validate_sandbox_environments(sandboxenv_type, environments)

    # proxy environments (for recording SandboxEvent)
    environments = {k: SandboxEnvironmentProxy(v) for k, v in environments.items()}

    try:
        # set context
        sandbox_environments_context_var.set(environments)
        sandbox_with_environments_context_var.set({})
        default_name = next(iter(environments.keys()))
        sandbox_default_context_var.set(default_name)

        # copy files into environments
        await copy_sandbox_environment_files(files, environments)

        # run setup script
        if setup:
            await setup_sandbox_environment(setup, environments)

        # return environments
        return environments

    except Exception as ex:
        environments = unproxy_environments(environments)
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
    environments = unproxy_environments(environments)
    await sample_cleanup(task_name, config, environments, interrupted)


def unproxy_environments(
    environments: dict[str, SandboxEnvironment],
) -> dict[str, SandboxEnvironment]:
    return {
        k: v._sandbox
        for k, v in cast(dict[str, SandboxEnvironmentProxy], environments).items()
    }


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
                    f"Environment referenced in sample file not found: '{envname}:{file}'. "
                    + "Note that ':' can be optionally used to specify an explicit environment name for sample files (e.g. 'envname:file') so cannot be used as a character within filenames."
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

    # execute and then remove setup script (don't retry it on timeout
    # in case it is not idempotent)
    try:
        await env.exec(["chmod", "+x", setup_file], timeout=30)
        result = await env.exec(
            ["env", setup_file], timeout=SANDBOX_SETUP_TIMEOUT, timeout_retry=False
        )
        if not result.success:
            raise RuntimeError(
                f"Failed to execute setup script for sample: {result.stderr}"
            )
        await env.exec(["rm", setup_file], timeout=30)
    except TimeoutError:
        raise RuntimeError("Timed out executing setup command in sandbox")


def default_sandbox_environment(
    environments: dict[str, SandboxEnvironment],
) -> SandboxEnvironment:
    default_name = sandbox_default_context_var.get()
    if default_name in environments:
        return environments[default_name]
    else:
        raise ValueError(
            f"Default sandbox environment '{default_name}' not found in environments"
        )


def validate_sandbox_environments(
    type: type[SandboxEnvironment], environments: dict[str, SandboxEnvironment]
) -> None:
    if len(environments) == 0:
        raise ValueError(
            "No environments returned from sample_init() method "
            + f"of '{type.__name__}'. Did you provide an implementation "
            + "of the sample_init() class method? "
        )


@contextmanager
def sandbox_default(name: str) -> Iterator[None]:
    """Set the default sandbox environment for the current context.

    Args:
       name: Sandbox to set as the default.
    """
    token = sandbox_default_context_var.set(name)
    try:
        yield
    finally:
        sandbox_default_context_var.reset(token)


sandbox_environments_context_var = ContextVar[dict[str, SandboxEnvironment]](
    "sandbox_environments"
)

sandbox_with_environments_context_var = ContextVar[dict[str, SandboxEnvironment]](
    "sandbox_with_environments"
)

sandbox_default_context_var = ContextVar[str]("sandbox_default")


async def _get_injection_target(
    injectables: list[SandboxInjectable],
) -> tuple[SandboxEnvironment, list[SandboxInjectable]]:
    """Find the best sandbox for injection and return it with needed injections.

    Args:
        injectables: List of detector/injector pairs to evaluate.

    Returns:
        Tuple of (sandbox_environment, needed_injections) where needed_injections
        contains only the injectables that require injection into the sandbox.

    Raises:
        ProcessLookupError: If no sandboxes are available.
    """
    environments = sandbox_environments_context_var.get(None)
    if not environments:
        raise_no_sandbox()

    # Find sandbox needing fewest injections
    best_candidate: tuple[SandboxEnvironment, list[SandboxInjectable]] | None = None
    for sb in environments.values():
        needed_injections = await _get_needed_injections(sb, injectables)

        if len(needed_injections) == 0:
            return sb, []
        elif best_candidate is None:
            best_candidate = (sb, needed_injections)
        elif len(needed_injections) < len(best_candidate[1]):
            best_candidate = (sb, needed_injections)

    if not best_candidate:
        raise_no_sandbox()

    return best_candidate


async def _get_needed_injections(
    sb: SandboxEnvironment, injectables: list[SandboxInjectable]
) -> list[SandboxInjectable]:
    """Get list of injections needed for this sandbox."""
    return [
        injectable for injectable in injectables if not await injectable.detector(sb)
    ]
