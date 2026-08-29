import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import pytest
from _pytest.mark import ParameterSet
from test_helpers.utils import is_docker_installed

import inspect_ai.util._sandbox.self_check as _self_check
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
)
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment

# Pull the portable check functions into this module so pytest collects them as
# tests, each driven by the `sandbox_env` fixture below.
from inspect_ai.util._sandbox.self_check import *  # noqa: F401, F403

# conftest wraps tests carrying this attribute in flaky_retry (docker execs
# flake in CI); checks xfail-marked via sandbox_env run once, unretried
for _name in _self_check.__all__:
    getattr(_self_check, _name)._needs_flaky_retry = True


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
    # Alpine's busybox coreutils differ from GNU, and this broke things in the past.
    SandboxConfig(
        id="docker-nonroot-alpine",
        env_type=DockerSandboxEnvironment,
        config=_compose("test_sandbox_compose_alpine.yaml"),
        requires_docker=True,
    ),
]


def _config_params() -> list[ParameterSet]:
    docker_installed = is_docker_installed()
    params = []
    for cfg in SANDBOX_CONFIGS:
        marks = [pytest.mark.slow]
        if cfg.requires_docker:
            marks.append(
                pytest.mark.skipif(
                    not docker_installed,
                    reason="Test doesn't work without Docker installed.",
                )
            )
        params.append(pytest.param(cfg, id=cfg.id, marks=marks))
    return params


class ConfigAndEnv(NamedTuple):
    cfg: SandboxConfig
    env: SandboxEnvironment


# Module-scoped: one env per config, shared by all checks (like the old
# self_check() runner) — a per-check env meant a docker compose up/down per
# check and tripled the slow-tools CI job. Checks must clean up after
# themselves. anyio's default anyio_backend fixture is module-scoped, so this
# works, and setup and teardown share the fixture's async context: the docker
# provider stashes running projects in a ContextVar during init and reads it
# back at cleanup — losing that context is the LookupError that sank
# https://github.com/UKGovernmentBEIS/inspect_ai/pull/347 under pytest-asyncio.
# Setup needs its own retry: conftest's flaky_retry wraps only test functions,
# and pytest caches a module-scoped fixture exception for the whole scope, so
# one transient `compose up` failure would fail all ~44 checks in one go.
async def _init_envs_with_retry(
    cfg: SandboxConfig, task_name: str
) -> dict[str, SandboxEnvironment]:
    attempts = 4  # aligned with conftest's flaky_retry(max_retries=3)
    for attempt in range(1, attempts + 1):
        try:
            await cfg.env_type.task_init(task_name=task_name, config=cfg.config)
            return await cfg.env_type.sample_init(
                task_name=task_name, config=cfg.config, metadata={}
            )
        except Exception:
            # tear down the half-initialized project so the next attempt (and,
            # on the last one, the test session) starts clean
            with contextlib.suppress(Exception):
                await cfg.env_type.task_cleanup(
                    task_name=task_name, config=cfg.config, cleanup=True
                )
            if attempt == attempts:
                raise
    raise AssertionError("unreachable")


@pytest.fixture(scope="module", params=_config_params())
async def _config_and_env(
    request,
) -> AsyncIterator[ConfigAndEnv]:
    cfg: SandboxConfig = request.param
    task_name = f"{__name__}_{cfg.id}"
    envs = await _init_envs_with_retry(cfg, task_name)
    try:
        yield ConfigAndEnv(cfg=cfg, env=envs["default"])
    finally:
        await cfg.env_type.sample_cleanup(
            task_name=task_name, config=cfg.config, environments=envs, interrupted=False
        )
        await cfg.env_type.task_cleanup(
            task_name=task_name, config=cfg.config, cleanup=True
        )


# Must stay function-scoped: xfails are applied per check via request.node.
@pytest.fixture
def sandbox_env(request, _config_and_env: ConfigAndEnv) -> SandboxEnvironment:
    # Known failures vary per sandbox, so apply them here rather than on the
    # (shared, provider-agnostic) check functions. originalname is the check's
    # function name without the parametrize suffix.
    reason = _config_and_env.cfg.xfails.get(request.node.originalname)
    if reason is not None:
        request.node.add_marker(pytest.mark.xfail(reason=reason, strict=True))

    return _config_and_env.env
