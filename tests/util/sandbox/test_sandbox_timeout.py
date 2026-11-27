from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Union
from unittest.mock import AsyncMock

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util import ExecResult, SandboxTimeoutError, SandboxTimeoutReason
from inspect_ai.util._sandbox import SandboxTimeoutError as InternalTimeoutError
from inspect_ai.util._sandbox import SandboxTimeoutReason as InternalTimeoutReason
from inspect_ai.util._sandbox.docker import compose as compose_module
from inspect_ai.util._sandbox.docker import docker as docker_module
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.docker.util import ComposeProject
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._subprocess import SubprocessRun


class TimeoutSandbox(SandboxEnvironment):
    """Mock sandbox that raises TimeoutError from all operations."""

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        raise TimeoutError("exec timed out")

    async def write_file(
        self, file: str, contents: str | bytes, *, user: str | None = None
    ) -> None:
        raise TimeoutError("write timed out")

    async def read_file(  # type: ignore[override]
        self, file: str, text: bool = True
    ) -> Union[str, bytes]:
        raise TimeoutError("read timed out")

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: object,
        environments: dict[str, "SandboxEnvironment"],
        interrupted: bool,
    ) -> None:
        pass


def test_sandbox_timeout_is_timeout_subclass() -> None:
    assert issubclass(SandboxTimeoutError, TimeoutError)


def test_timeout_reason_public_contract() -> None:
    assert SandboxTimeoutError is InternalTimeoutError
    assert SandboxTimeoutReason is InternalTimeoutReason
    error = SandboxTimeoutError("deadline")
    assert str(error) == "deadline"
    assert error.truncated_output is None
    assert error.reason is None
    classified = SandboxTimeoutError("deadline", "partial", reason="command")
    assert classified.truncated_output == "partial"
    assert classified.reason == "command"


def test_timeout_reason_is_keyword_only() -> None:
    constructor: Callable[..., SandboxTimeoutError] = SandboxTimeoutError
    with pytest.raises(TypeError):
        constructor("deadline", None, "command")


@pytest.mark.parametrize("reason", [None, "command", "no_response", "unknown"])
@pytest.mark.parametrize("output", [None, "partial output before timeout"])
async def test_exec_preserves_classified_timeout(
    monkeypatch: pytest.MonkeyPatch,
    reason: SandboxTimeoutReason | None,
    output: str | None,
) -> None:
    error = SandboxTimeoutError(
        "exec timed out", truncated_output=output, reason=reason
    )
    provider = TimeoutSandbox()
    monkeypatch.setattr(provider, "exec", AsyncMock(side_effect=error))
    with pytest.raises(SandboxTimeoutError) as raised:
        await SandboxEnvironmentProxy(provider).exec(["cmd"])
    assert raised.value is error
    assert raised.value.reason == reason
    assert raised.value.truncated_output == output
    assert str(raised.value) == "exec timed out"


async def test_exec_timeout_converted() -> None:
    proxy = SandboxEnvironmentProxy(TimeoutSandbox())
    with pytest.raises(SandboxTimeoutError):
        await proxy.exec(["cmd"])


async def test_write_file_timeout_converted() -> None:
    proxy = SandboxEnvironmentProxy(TimeoutSandbox())
    with pytest.raises(SandboxTimeoutError):
        await proxy.write_file("test.txt", "content")


async def test_read_file_timeout_converted() -> None:
    proxy = SandboxEnvironmentProxy(TimeoutSandbox())
    with pytest.raises(SandboxTimeoutError):
        await proxy.read_file("test.txt")


async def test_sandbox_timeout_caught_by_timeout_error() -> None:
    """SandboxTimeoutError should be catchable as TimeoutError."""
    proxy = SandboxEnvironmentProxy(TimeoutSandbox())
    with pytest.raises(TimeoutError):
        await proxy.exec(["cmd"])


class TimeoutWithOutputSandbox(TimeoutSandbox):
    """Mock sandbox whose exec timeout carries partial output (as docker does)."""

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        err = TimeoutError("exec timed out")
        setattr(err, "truncated_output", "partial output before timeout")
        raise err


async def test_exec_timeout_carries_truncated_output() -> None:
    proxy = SandboxEnvironmentProxy(TimeoutWithOutputSandbox())
    with pytest.raises(SandboxTimeoutError) as exc_info:
        await proxy.exec(["cmd"])
    assert type(exc_info.value) is SandboxTimeoutError
    assert exc_info.value.reason is None
    assert exc_info.value.truncated_output == "partial output before timeout"


async def test_exec_timeout_truncated_output_defaults_none() -> None:
    proxy = SandboxEnvironmentProxy(TimeoutSandbox())
    with pytest.raises(SandboxTimeoutError) as exc_info:
        await proxy.exec(["cmd"])
    assert type(exc_info.value) is SandboxTimeoutError
    assert isinstance(exc_info.value.__cause__, TimeoutError)
    assert exc_info.value.reason is None
    assert exc_info.value.truncated_output is None


@pytest.mark.parametrize("catch_type", [SandboxTimeoutError, TimeoutError])
async def test_classified_timeout_caught_by_existing_handlers(
    monkeypatch: pytest.MonkeyPatch,
    catch_type: type[TimeoutError],
) -> None:
    provider = TimeoutSandbox()
    monkeypatch.setattr(
        provider,
        "exec",
        AsyncMock(side_effect=SandboxTimeoutError("deadline", reason="command")),
    )
    with pytest.raises(catch_type):
        await SandboxEnvironmentProxy(provider).exec(["cmd"])


async def test_local_command_deadline_is_classified() -> None:
    provider = LocalSandboxEnvironment()
    try:
        with pytest.raises(SandboxTimeoutError) as raised:
            await SandboxEnvironmentProxy(provider).exec(["sleep", "30"], timeout=1)
    finally:
        await LocalSandboxEnvironment.sample_cleanup(
            "test", None, {"default": provider}, False
        )
    assert raised.value.reason == "command"
    assert isinstance(raised.value.__cause__, TimeoutError)


def _docker_proxy() -> SandboxEnvironmentProxy:
    project = ComposeProject(
        name="test", config=None, sample_id=None, epoch=None, env=None
    )
    return SandboxEnvironmentProxy(
        DockerSandboxEnvironment("default", project, "/work")
    )


@pytest.mark.parametrize(
    "returncode,elapsed",
    [(124, 30.0), (137, 30.0), (143, 30.0), (124, 31.0), (137, 31.0), (143, 31.0)],
)
@pytest.mark.parametrize("streams", [("", ""), ("partial out", "partial err")])
async def test_docker_command_deadline_is_distinct(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    elapsed: float,
    streams: tuple[str, str],
) -> None:
    clock = iter([100.0, 100.0 + elapsed])
    monkeypatch.setattr(
        docker_module, "time", SimpleNamespace(monotonic=lambda: next(clock))
    )
    run = AsyncMock(
        return_value=SubprocessRun(
            result=ExecResult(
                success=False,
                returncode=returncode,
                stdout=streams[0],
                stderr=streams[1],
            ),
            stdin_written=True,
        )
    )
    monkeypatch.setattr(compose_module, "run_subprocess", run)
    with pytest.raises(SandboxTimeoutError) as raised:
        await _docker_proxy().exec(["sleep", "300"], timeout=30)
    assert raised.value.reason == "command"
    assert str(raised.value) == "Command timed out after 30 seconds"
    assert raised.value.truncated_output == (
        "partial outpartial err" if streams[0] else None
    )
    run.assert_awaited_once()


@pytest.mark.parametrize("retry", [False, True])
async def test_docker_host_timeout_is_no_response(
    monkeypatch: pytest.MonkeyPatch,
    retry: bool,
) -> None:
    run = AsyncMock(side_effect=TimeoutError("host stopped answering"))
    monkeypatch.setattr(compose_module, "run_subprocess", run)
    with pytest.raises(SandboxTimeoutError) as raised:
        await _docker_proxy().exec(
            ["sleep", "300"], timeout=30, timeout_retry=retry, concurrency=False
        )
    assert type(raised.value) is SandboxTimeoutError
    assert raised.value.reason == "no_response"
    assert raised.value.truncated_output is None
    assert "Docker compose command" in str(raised.value)
    assert isinstance(raised.value.__cause__, TimeoutError)
    assert [call.kwargs["timeout"] for call in run.await_args_list] == (
        [40, 40, 20] if retry else [40]
    )


@pytest.mark.parametrize(
    "returncode,timeout,elapsed",
    [
        (124, 30, 0.0),
        (124, 30, 29.0),
        (137, 30, 29.0),
        (143, 30, 29.0),
        (124, None, 31.0),
        (137, None, 31.0),
        (143, None, 31.0),
    ],
)
async def test_docker_non_deadline_exit_is_an_ordinary_result(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    timeout: int | None,
    elapsed: float,
) -> None:
    clock = iter([100.0, 100.0 + elapsed])
    monkeypatch.setattr(
        docker_module, "time", SimpleNamespace(monotonic=lambda: next(clock))
    )
    result = ExecResult(
        success=False, returncode=returncode, stdout="ordinary output", stderr=""
    )
    monkeypatch.setattr(
        compose_module,
        "run_subprocess",
        AsyncMock(return_value=SubprocessRun(result=result, stdin_written=True)),
    )
    proxy = _docker_proxy()
    with proxy.no_events():
        assert await proxy.exec(["cmd"], timeout=timeout) is result


@pytest.fixture
async def timeout_docker_environment(
    request: pytest.FixtureRequest,
) -> AsyncIterator[DockerSandboxEnvironment]:
    task_name = f"{__name__}_{request.node.name}"
    await DockerSandboxEnvironment.task_init(task_name=task_name, config=None)
    try:
        environments = await DockerSandboxEnvironment.sample_init(
            task_name=task_name, config=None, metadata={}
        )
        try:
            yield environments["default"].as_type(DockerSandboxEnvironment)
        finally:
            await DockerSandboxEnvironment.sample_cleanup(
                task_name=task_name,
                config=None,
                environments=environments,
                interrupted=False,
            )
    finally:
        await DockerSandboxEnvironment.task_cleanup(
            task_name=task_name, config=None, cleanup=True
        )


@skip_if_no_docker
@pytest.mark.slow
async def test_docker_real_command_deadline_cleans_up_process(
    timeout_docker_environment: DockerSandboxEnvironment,
) -> None:
    proxy = SandboxEnvironmentProxy(timeout_docker_environment)
    with pytest.raises(SandboxTimeoutError) as raised:
        await proxy.exec(
            [
                "sh",
                "-c",
                "set -e; echo $$ > /tmp/inspect-timeout.pid; printf partial; exec sleep 300",
            ],
            timeout=2,
        )
    assert raised.value.reason == "command"
    assert raised.value.truncated_output == "partial"
    result = await timeout_docker_environment.exec(
        [
            "sh",
            "-c",
            'pid=$(cat /tmp/inspect-timeout.pid) && ! kill -0 "$pid" 2>/dev/null',
        ],
        timeout=30,
    )
    assert result.success
