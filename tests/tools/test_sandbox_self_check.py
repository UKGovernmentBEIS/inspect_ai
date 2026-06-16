import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
)
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment

# Pull the portable check functions into this module so pytest collects them as
# tests, each driven by the `sandbox_env` fixture below.
from inspect_ai.util._sandbox.self_check import *  # noqa: F401, F403


@dataclass
class SandboxConfig:
    """A sandbox to run the self-check suite against.

    Attributes:
        id: pytest parameter id (the `[...]` suffix on each generated case).
        env_type: the SandboxEnvironment implementation under test.
        config: path to a compose file, or None for the provider default.
        requires_docker: skip these cases when Docker isn't installed.
        xfails: check name -> reason, for checks this sandbox can't satisfy.
    """

    id: str
    env_type: type[SandboxEnvironment]
    config: str | None
    requires_docker: bool
    xfails: dict[str, str] = field(default_factory=dict)


def _compose(name: str) -> str:
    return str(Path(__file__).parent / name)


SANDBOX_CONFIGS = [
    SandboxConfig(
        id="local",
        env_type=LocalSandboxEnvironment,
        config=None,
        requires_docker=False,
        xfails={
            "test_exec_as_user": "local sandbox ignores the user= parameter",
            "test_exec_as_nonexistent_user": "local sandbox ignores the user= parameter",
            "test_exec_timeout_not_raised_on_fast_signal_death": (
                "local sandbox doesn't wrap commands with in-container `timeout`, so "
                "the signal exit code semantics differ (returns -15 not 143)"
            ),
        },
    ),
    # Default docker-compose runs as root, which can overwrite read-only files.
    SandboxConfig(
        id="docker-root",
        env_type=DockerSandboxEnvironment,
        config=None,
        requires_docker=True,
        xfails={
            "test_write_text_file_without_permissions": "root can overwrite a read-only file",
            "test_write_binary_file_without_permissions": "root can overwrite a read-only file",
        },
    ),
    # A non-root user, so read-only/permission semantics hold.
    SandboxConfig(
        id="docker-nonroot",
        env_type=DockerSandboxEnvironment,
        config=_compose("test_sandbox_compose.yaml"),
        requires_docker=True,
    ),
    # Alpine's busybox coreutils differ from GNU. (The without-permissions checks
    # used to be expected failures here because the old write_file used `cp`; it
    # now uses `tee`, which respects the read-only bit on busybox too.)
    SandboxConfig(
        id="docker-nonroot-alpine",
        env_type=DockerSandboxEnvironment,
        config=_compose("test_sandbox_compose_alpine.yaml"),
        requires_docker=True,
    ),
]


def _docker_available() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "--version"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).returncode
            == 0
        )
    except FileNotFoundError:
        return False


_DOCKER_AVAILABLE = _docker_available()


def _config_params() -> list:
    params = []
    for cfg in SANDBOX_CONFIGS:
        marks = [pytest.mark.slow]
        if cfg.requires_docker:
            marks.append(
                pytest.mark.skipif(
                    not _DOCKER_AVAILABLE,
                    reason="Test doesn't work without Docker installed.",
                )
            )
        params.append(pytest.param(cfg, id=cfg.id, marks=marks))
    return params


@pytest.fixture(params=_config_params())
async def sandbox_env(request) -> AsyncIterator[SandboxEnvironment]:
    cfg: SandboxConfig = request.param

    # Known failures vary per sandbox, so apply them here rather than on the
    # (shared, provider-agnostic) check functions. originalname is the check's
    # function name without the parametrize suffix.
    reason = cfg.xfails.get(request.node.originalname)
    if reason is not None:
        request.node.add_marker(pytest.mark.xfail(reason=reason, strict=True))

    # task_init/sample_init and their cleanups run in this fixture's async
    # context, which is the test's context too. The docker provider stashes
    # running projects in a ContextVar during init and reads it back at cleanup;
    # keeping both in one context avoids the LookupError that sank
    # https://github.com/UKGovernmentBEIS/inspect_ai/pull/347 under pytest-asyncio.
    task_name = f"{__name__}_{cfg.id}_{request.node.originalname}"
    await cfg.env_type.task_init(task_name=task_name, config=cfg.config)
    envs = await cfg.env_type.sample_init(
        task_name=task_name, config=cfg.config, metadata={}
    )
    try:
        yield envs["default"]
    finally:
        await cfg.env_type.sample_cleanup(
            task_name=task_name, config=cfg.config, environments=envs, interrupted=False
        )
        await cfg.env_type.task_cleanup(
            task_name=task_name, config=cfg.config, cleanup=True
        )
