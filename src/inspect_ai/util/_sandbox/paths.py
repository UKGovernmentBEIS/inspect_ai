import os
from pathlib import Path

from inspect_ai.util._sandbox.compose import ComposeBuild, ComposeConfig
from inspect_ai.util._sandbox.environment import SandboxEnvironmentConfigType


def resolve_config_paths(
    config: SandboxEnvironmentConfigType | None, task_dir: str
) -> SandboxEnvironmentConfigType | None:
    """Make a sandbox config's relative paths absolute against the task directory.

    A relative string config, and each relative build context of a
    `ComposeConfig` service, becomes absolute when that path exists under
    `task_dir`. The result keeps any `..` segments, so a path through a
    directory symlink names the same file it does relative to `task_dir`. An
    omitted `ComposeBuild.context` means the compose default `"."`, so it
    becomes `task_dir` itself. A URI, an absolute path, and a string naming no
    file under `task_dir` (inline JSON, or a path to resolve against the
    launch directory) are returned as given. Other config types are returned
    as given.

    For an absolute `task_dir` the result does not depend on the working
    directory, so setup and sample start resolve a config to the same value.
    The config passed in is not modified.

    Args:
        config: Sandbox config.
        task_dir: Directory of the task's source file.

    Returns:
        The config with its paths resolved.
    """
    if isinstance(config, str):
        return _resolve_path(config, task_dir)
    elif isinstance(config, ComposeConfig):
        return _resolve_compose_config(config, task_dir)
    else:
        return config


def _resolve_path(path: str, task_dir: str) -> str:
    if "://" in path or os.path.isabs(path):
        return path
    # not normalised: collapsing `..` lexically would change the target of a
    # path that runs through a directory symlink
    candidate = os.path.join(os.getcwd(), task_dir, path)
    # os.path.exists returns False on OSError and ValueError (e.g. a string
    # too long to be a path, or one with a null byte)
    if os.path.exists(candidate):
        return Path(candidate).as_posix()
    else:
        return path


def _resolve_compose_config(config: ComposeConfig, task_dir: str) -> ComposeConfig:
    services = dict(config.services)
    changed = False
    for name, service in config.services.items():
        build = service.build
        if isinstance(build, str):
            resolved: str | ComposeBuild = _resolve_path(build, task_dir)
        elif isinstance(build, ComposeBuild):
            context = build.context if build.context is not None else "."
            resolved_context = _resolve_path(context, task_dir)
            resolved = (
                build
                if resolved_context == context
                else build.model_copy(update={"context": resolved_context})
            )
        else:
            continue
        if resolved != build:
            services[name] = service.model_copy(update={"build": resolved})
            changed = True
    return config.model_copy(update={"services": services}) if changed else config
