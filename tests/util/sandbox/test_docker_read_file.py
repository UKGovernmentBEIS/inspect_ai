import errno
import io
import shlex
import shutil
import tarfile
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import anyio
import pytest
import yaml
from anyio.abc import ByteReceiveStream
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util._checkpoint._copy import copy_out
from inspect_ai.util._sandbox.docker import compose as compose_module
from inspect_ai.util._sandbox.docker import docker as docker_module
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.docker.util import ComposeProject
from inspect_ai.util._sandbox.environment import (
    SandboxUnavailableError,
    SandboxUserUnsupportedError,
)
from inspect_ai.util._sandbox.limits import (
    OutputLimitExceededError,
    override_max_exec_output_size,
    override_max_read_file_size,
)
from inspect_ai.util._subprocess import ExecResult, StdoutReader


def _environment() -> DockerSandboxEnvironment:
    project = ComposeProject(
        name="test",
        config=None,
        sample_id=None,
        epoch=None,
        env=None,
    )
    return DockerSandboxEnvironment("default", project, "/work")


def _archive(*members: tuple[str, bytes, bytes]) -> bytes:
    """Build a tar archive from (name, tar type, data) entries."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, type, data in members:
            info = tarfile.TarInfo(name)
            info.type = type
            if type == tarfile.SYMTYPE or type == tarfile.LNKTYPE:
                info.linkname = "/etc/passwd"
            info.size = len(data) if type == tarfile.REGTYPE else 0
            tar.addfile(info, io.BytesIO(data) if type == tarfile.REGTYPE else None)
    return buffer.getvalue()


def _copy_returning(archive: bytes) -> AsyncMock:
    """Fake `compose_read_archive` that streams `archive` to its reader."""

    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(archive), 4096):
            yield archive[start : start + 4096]

    async def copy(
        service: str,
        file: str,
        project: ComposeProject,
        read_archive: StdoutReader,
        user: str | None = None,
    ) -> bytes:
        return await read_archive(cast(ByteReceiveStream, chunks()))

    return AsyncMock(side_effect=copy)


@pytest.mark.parametrize("file", [".", "./", "..", "../", "dir/.", "dir/../"])
async def test_read_file_rejects_directory_alias_before_copy(
    file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment()
    exec_mock = AsyncMock()
    copy_mock = AsyncMock()
    monkeypatch.setattr(environment, "exec", exec_mock)
    monkeypatch.setattr(docker_module, "compose_read_archive", copy_mock)

    with pytest.raises(IsADirectoryError) as ex:
        await environment.read_file(file)

    assert file in str(ex.value)
    exec_mock.assert_not_awaited()
    copy_mock.assert_not_awaited()


async def test_read_file_returns_archived_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    exec_mock = AsyncMock()
    copy_mock = _copy_returning(_archive(("source.txt", tarfile.REGTYPE, b"hi\r\n")))
    monkeypatch.setattr(environment, "exec", exec_mock)
    monkeypatch.setattr(docker_module, "compose_read_archive", copy_mock)

    assert await environment.read_file("/sandbox/source.txt", text=False) == b"hi\r\n"
    assert await environment.read_file("/sandbox/source.txt") == "hi\r\n"

    assert copy_mock.await_args is not None
    assert copy_mock.await_args.kwargs["service"] == "default"
    assert copy_mock.await_args.kwargs["file"] == "/sandbox/source.txt"
    assert copy_mock.await_args.kwargs["project"] is environment._project
    exec_mock.assert_not_awaited()


async def test_read_file_allows_empty_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    copy_mock = _copy_returning(_archive(("empty", tarfile.REGTYPE, b"")))
    monkeypatch.setattr(docker_module, "compose_read_archive", copy_mock)

    assert await environment.read_file("empty", text=False) == b""


async def test_read_file_rejects_directory_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    copy_mock = _copy_returning(
        _archive(
            ("directory", tarfile.DIRTYPE, b""),
            ("directory/child", tarfile.REGTYPE, b"child"),
        )
    )
    monkeypatch.setattr(docker_module, "compose_read_archive", copy_mock)

    with pytest.raises(IsADirectoryError) as ex:
        await environment.read_file("directory")

    assert ex.value.filename == "directory"


@pytest.mark.parametrize(
    "archive",
    [
        pytest.param(_archive(), id="empty-archive"),
        pytest.param(b"\0" * 1024, id="docker-empty-archive"),
        pytest.param(b"", id="no-output"),
        pytest.param(_archive(("source", tarfile.SYMTYPE, b"")), id="symlink"),
        pytest.param(_archive(("source", tarfile.LNKTYPE, b"")), id="hardlink"),
        pytest.param(_archive(("source", tarfile.FIFOTYPE, b"")), id="fifo"),
        pytest.param(
            _archive(
                ("source", tarfile.REGTYPE, b"first"),
                ("source/child", tarfile.REGTYPE, b"second"),
            ),
            id="extra-entry",
        ),
    ],
)
async def test_read_file_rejects_anything_but_one_regular_file(
    archive: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment()
    monkeypatch.setattr(docker_module, "compose_read_archive", _copy_returning(archive))

    with pytest.raises(OSError) as ex:
        await environment.read_file("source")

    assert ex.value.errno == errno.EINVAL
    assert ex.value.filename == "source"


async def test_read_file_uses_kernel_permissions_instead_of_archive_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("unreadable.txt")
        info.size = len(b"secret")
        info.mode = 0o244
        tar.addfile(info, io.BytesIO(b"secret"))
    monkeypatch.setattr(
        docker_module, "compose_read_archive", _copy_returning(buffer.getvalue())
    )

    assert await environment.read_file("unreadable.txt") == "secret"


async def test_read_file_rejects_invalid_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    monkeypatch.setattr(
        docker_module, "compose_read_archive", _copy_returning(b"not a tar archive")
    )

    with pytest.raises(RuntimeError, match="invalid archive"):
        await environment.read_file("source")


async def test_read_file_enforces_size_limit_on_archived_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()

    with override_max_read_file_size(10):
        over = _copy_returning(_archive(("big", tarfile.REGTYPE, b"x" * 11)))
        monkeypatch.setattr(docker_module, "compose_read_archive", over)
        with pytest.raises(OutputLimitExceededError):
            await environment.read_file("big")

        at = _copy_returning(_archive(("big", tarfile.REGTYPE, b"x" * 10)))
        monkeypatch.setattr(docker_module, "compose_read_archive", at)
        assert await environment.read_file("big") == "x" * 10


@pytest.mark.parametrize(
    "archive,expected",
    [
        pytest.param(
            _archive(
                ("directory", tarfile.DIRTYPE, b""),
                ("directory/child", tarfile.REGTYPE, b"x" * 100_000),
            ),
            IsADirectoryError,
            id="directory",
        ),
        pytest.param(
            _archive(("big", tarfile.REGTYPE, b"x" * 100_000)),
            OutputLimitExceededError,
            id="file",
        ),
        pytest.param(b"x" * 100_000, OutputLimitExceededError, id="unparseable"),
        pytest.param(b"\0" * 100_000, OutputLimitExceededError, id="zeros"),
    ],
)
async def test_read_file_stops_archive_over_limit(
    archive: bytes, expected: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment()
    monkeypatch.setattr(docker_module, "compose_read_archive", _copy_returning(archive))

    with override_max_read_file_size(10):
        with pytest.raises(expected):
            await environment.read_file("source")


@pytest.mark.parametrize(
    "docker_error",
    [
        "Could not find the file in the container",
        "Error response from daemon: no such file or directory",
    ],
)
async def test_read_file_preserves_missing_file_error(
    docker_error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    copy_mock = AsyncMock(side_effect=RuntimeError(docker_error))
    monkeypatch.setattr(docker_module, "compose_read_archive", copy_mock)

    with pytest.raises(FileNotFoundError) as ex:
        await environment.read_file("missing")

    assert ex.value.filename == "missing"
    copy_mock.assert_awaited_once()


@pytest.mark.parametrize(
    "returncode,stdout,stderr",
    [
        (
            127,
            b'OCI runtime exec failed: exec: "/usr/bin/timeout": '
            b"stat /usr/bin/timeout: no such file or directory\r\n",
            b"",
        ),
        (
            127,
            b"",
            b'OCI runtime exec failed: exec: "/usr/bin/timeout": '
            b"stat /usr/bin/timeout: no such file or directory\n",
        ),
        (
            127,
            b"",
            b"/usr/bin/timeout: failed to run command '/bin/sh': No such file or directory\n",
        ),
        (
            127,
            b"",
            b"timeout: can't execute '/bin/sh': No such file or directory\n",
        ),
        (127, b"", b"sh: exec: tar: not found\n"),
        (
            126,
            b'OCI runtime exec failed: exec: "/usr/bin/timeout": permission denied\r\n',
            b"",
        ),
        (
            126,
            b"",
            b"/usr/bin/timeout: failed to run command '/bin/sh': Permission denied\n",
        ),
        (126, b"", b"sh: exec: tar: Permission denied\n"),
    ],
)
async def test_read_file_preserves_execution_machinery_errors(
    returncode: int, stdout: bytes, stderr: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        compose_module,
        "compose_command",
        AsyncMock(
            return_value=ExecResult(
                success=False, returncode=returncode, stdout=stdout, stderr=stderr
            )
        ),
    )

    with pytest.raises(SandboxUnavailableError, match="required tools") as ex:
        await _environment().read_file("no such file or directory")
    assert (stderr or stdout).decode().strip() in str(ex.value)


@pytest.mark.parametrize("user", [None, "agent"])
async def test_read_file_command_preserves_user_and_archive_options(
    user: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    command_mock = AsyncMock(
        return_value=ExecResult(
            success=True,
            returncode=0,
            stdout=_archive(("source", tarfile.REGTYPE, b"contents")),
            stderr=b"",
        )
    )
    monkeypatch.setattr(compose_module, "compose_command", command_mock)
    file = "/tmp/source with 'quotes'\nand spaces"

    assert await _environment().read_file(file, user=user) == "contents"

    command_mock.assert_awaited_once()
    assert command_mock.await_args is not None
    command = command_mock.await_args.args[0]
    options = command[: command.index("default")]
    assert options[0] == "exec"
    assert "-T" in options
    assert options[options.index("--workdir") + 1] == "/"
    for setting in ("LC_ALL=C", "TAR_OPTIONS="):
        assert options[options.index(setting) - 1] == "--env"
    if user is None:
        assert "--user" not in options
    else:
        assert options[options.index("--user") + 1] == user
    assert command[-6:] == ["tar", "-chf", "-", "--no-recursion", "--", file]
    assert command_mock.await_args.kwargs["text"] is False


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_read_file_reports_stopped_container_as_unavailable(
    stream: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    diagnostic = b'service "no such file or directory" is not running\r\n'
    monkeypatch.setattr(
        compose_module,
        "compose_command",
        AsyncMock(
            return_value=ExecResult(
                success=False,
                returncode=1,
                stdout=diagnostic if stream == "stdout" else b"",
                stderr=diagnostic if stream == "stderr" else b"",
            )
        ),
    )

    with pytest.raises(SandboxUnavailableError, match="not running"):
        await _environment().read_file("source")


@pytest.mark.parametrize("returncode", [137, 143])
@pytest.mark.parametrize("partial_output", [False, True])
async def test_read_file_signal_exit_before_timeout_is_a_runtime_error(
    returncode: int, partial_output: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        compose_module,
        "compose_command",
        AsyncMock(
            return_value=ExecResult(
                success=False,
                returncode=returncode,
                stdout=b"partial archive" if partial_output else b"",
                stderr=b"tar: Removing leading `/' from member names\n"
                if partial_output
                else b"",
            )
        ),
    )

    with pytest.raises(RuntimeError) as ex:
        await _environment().read_file("source")
    assert type(ex.value) is RuntimeError


@pytest.mark.parametrize(
    "stderr,expected",
    [
        (b"tar: /missing: Cannot stat: No such file or directory\n", FileNotFoundError),
        (b"tar: /private: Cannot open: Permission denied\n", PermissionError),
    ],
)
async def test_read_file_preserves_tar_file_errors(
    stderr: bytes, expected: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        compose_module,
        "compose_command",
        AsyncMock(
            return_value=ExecResult(
                success=False, returncode=2, stdout=b"", stderr=stderr
            )
        ),
    )
    with pytest.raises(expected):
        await _environment().read_file("source")


@pytest.mark.parametrize(
    "returncode,stdout,stderr",
    [
        (
            1,
            b"",
            b"Error response from daemon: unable to find user agent: "
            b"no matching entries in passwd file\n",
        ),
        (
            126,
            b"unable to find user agent: no matching entries in passwd file\r\n",
            b"",
        ),
    ],
    ids=["engine-29", "engine-28"],
)
async def test_read_file_reports_unknown_user_as_unsupported(
    returncode: int, stdout: bytes, stderr: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        compose_module,
        "compose_command",
        AsyncMock(
            return_value=ExecResult(
                success=False, returncode=returncode, stdout=stdout, stderr=stderr
            )
        ),
    )
    with pytest.raises(SandboxUserUnsupportedError):
        await _environment().read_file("source", user="agent")


@pytest.mark.parametrize("contents", [b"contents", b""])
@pytest.mark.parametrize(
    "stderr",
    [
        b"tar: source: file changed as we read it\n",
        b"tar: Removing leading `/' from member names\n"
        b"tar: Removing leading `/' from hard link targets\n"
        b"tar: source: file changed as we read it\n",
        b"tar: Removing leading '/' from member names\n"
        b"tar: Removing leading '/' from hard link targets\n"
        b"tar: 'source with spaces': file changed as we read it\n",
    ],
)
async def test_read_file_accepts_changed_file_warning(
    contents: bytes, stderr: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        compose_module,
        "compose_command",
        AsyncMock(
            return_value=ExecResult(
                success=False,
                returncode=1,
                stdout=_archive(("source", tarfile.REGTYPE, contents)),
                stderr=stderr,
            )
        ),
    )
    assert await _environment().read_file("source", text=False) == contents


@pytest.mark.parametrize(
    "returncode,stderr",
    [
        (1, b""),
        (1, b"tar: source: File shrank by 1 byte; padding with zeros\n"),
        (
            1,
            b"tar: source: File shrank by 1 byte; padding with zeros\n"
            b"tar: source: file changed as we read it\n",
        ),
        (1, b"tar: short read\n"),
        (
            1,
            b"tar: source: Read error\ntar: source: file changed as we read it\n",
        ),
        (2, b"tar: source: file changed as we read it\n"),
    ],
)
async def test_read_file_rejects_other_errors_despite_valid_archive(
    returncode: int, stderr: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        compose_module,
        "compose_command",
        AsyncMock(
            return_value=ExecResult(
                success=False,
                returncode=returncode,
                stdout=_archive(("source", tarfile.REGTYPE, b"contents")),
                stderr=stderr,
            )
        ),
    )
    with pytest.raises(RuntimeError):
        await _environment().read_file("source")


async def test_read_file_rejects_potentially_truncated_changed_file_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderr = b"tar: source: file changed as we read it\n"
    monkeypatch.setattr(
        compose_module,
        "compose_command",
        AsyncMock(
            return_value=ExecResult(
                success=False,
                returncode=1,
                stdout=_archive(("source", tarfile.REGTYPE, b"contents")),
                stderr=stderr,
            )
        ),
    )
    with override_max_exec_output_size(len(stderr)):
        with pytest.raises(RuntimeError):
            await _environment().read_file("source")


@pytest.mark.parametrize(
    "archive,expected",
    [
        (b"invalid archive", RuntimeError),
        (_archive(("source", tarfile.SYMTYPE, b"")), OSError),
        (
            _archive(
                ("source", tarfile.REGTYPE, b"one"),
                ("extra", tarfile.REGTYPE, b"two"),
            ),
            OSError,
        ),
        (_archive(("source", tarfile.REGTYPE, b"too big")), OutputLimitExceededError),
    ],
)
async def test_read_file_validates_archive_after_changed_file_warning(
    archive: bytes, expected: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        compose_module,
        "compose_command",
        AsyncMock(
            return_value=ExecResult(
                success=False,
                returncode=1,
                stdout=archive,
                stderr=b"tar: source: file changed as we read it\n",
            )
        ),
    )
    with override_max_read_file_size(4):
        with pytest.raises(expected):
            await _environment().read_file("source")


@pytest.fixture
async def docker_environment(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> AsyncIterator[DockerSandboxEnvironment]:
    task_name = f"{__name__}_{request.node.name}"
    config = getattr(request, "param", None)
    if isinstance(config, dict):
        config_file = tmp_path / "compose.yaml"
        config_file.write_text(yaml.safe_dump(config))
        config = str(config_file)
    await DockerSandboxEnvironment.task_init(task_name=task_name, config=config)
    environments = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=config, metadata={}
    )

    try:
        yield environments["default"].as_type(DockerSandboxEnvironment)
    finally:
        await DockerSandboxEnvironment.sample_cleanup(
            task_name=task_name,
            config=config,
            environments=environments,
            interrupted=False,
        )
        await DockerSandboxEnvironment.task_cleanup(
            task_name=task_name, config=config, cleanup=True
        )


@pytest.mark.slow
@skip_if_no_docker
async def test_docker_read_file_reports_stopped_container_as_unavailable(
    docker_environment: DockerSandboxEnvironment,
) -> None:
    env = docker_environment
    await env.write_file("/tmp/recording", "contents")
    result = await compose_module.compose_command(
        ["stop", env._service], project=env._project, timeout=60
    )
    assert result.success, result.stderr

    with pytest.raises(SandboxUnavailableError, match="not running"):
        await env.read_file("/tmp/recording")


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize(
    "docker_environment",
    [None, str(Path(__file__).parents[2] / "tools/test_sandbox_compose_alpine.yaml")],
    indirect=True,
    ids=["gnu", "busybox"],
)
@pytest.mark.parametrize("change", ["grow", "shrink"])
async def test_docker_read_file_changing_during_read(
    docker_environment: DockerSandboxEnvironment,
    change: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = docker_environment
    size = 32 * 1024 * 1024
    file = f"/tmp/inspect-read-changing-{uuid4().hex}-quote'\nname"
    setup = await env.exec(
        [
            "/bin/sh",
            "-c",
            'set -e; dd if=/dev/zero of="$1" bs=1048576 count=32 2>/dev/null; '
            'chmod 644 "$1"',
            "sh",
            file,
        ],
        user="root",
    )
    assert setup.success, setup.stderr
    started, mutated = anyio.Event(), anyio.Event()
    original_reader = docker_module._read_archive

    async def read_archive(
        stream: ByteReceiveStream, limit: int, original_file: str
    ) -> bytes:
        async def chunks() -> AsyncIterator[bytes]:
            async for part in stream:
                if not started.is_set():
                    started.set()
                    await mutated.wait()
                yield part

        return await original_reader(
            cast(ByteReceiveStream, chunks()), limit, original_file
        )

    monkeypatch.setattr(docker_module, "_read_archive", read_archive)

    async def read() -> None:
        if change == "grow":
            assert await env.read_file(file, text=False, user="65534") == bytes(size)
        else:
            with pytest.raises(RuntimeError):
                await env.read_file(file, user="65534")

    with anyio.fail_after(30):
        async with anyio.create_task_group() as tg:
            tg.start_soon(read)
            await started.wait()
            mutation = (
                'printf extra >> "$1"' if change == "grow" else 'printf short > "$1"'
            )
            result = await env.exec(
                ["/bin/sh", "-c", mutation, "sh", file],
                user="root",
                concurrency=False,
            )
            assert result.success, result.stderr
            mutated.set()


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize(
    "docker_environment",
    [None, str(Path(__file__).parents[2] / "tools/test_sandbox_compose_alpine.yaml")],
    indirect=True,
    ids=["gnu", "busybox"],
)
async def test_docker_read_file_without_read_bits_uses_kernel_permissions(
    docker_environment: DockerSandboxEnvironment,
) -> None:
    env = docker_environment
    file = f"/tmp/inspect-read-permissions-{uuid4().hex}"
    await env.write_file(file, "contents", user="root")
    assert (await env.exec(["chmod", "000", file], user="root")).success

    assert await env.read_file(file, user="root") == "contents"
    with pytest.raises(PermissionError):
        await env.read_file(file, user="65534")


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize(
    "docker_environment",
    [None, str(Path(__file__).parents[2] / "tools/test_sandbox_compose_alpine.yaml")],
    indirect=True,
    ids=["gnu", "busybox"],
)
@pytest.mark.parametrize("tool", ["/usr/bin/timeout", "/bin/sh", "tar"])
async def test_docker_read_file_missing_execution_machinery(
    docker_environment: DockerSandboxEnvironment, tool: str
) -> None:
    env = docker_environment
    file = f"/tmp/inspect-read-dependency-{uuid4().hex}"
    await env.write_file(file, "exists", user="root")
    paths = [tool] if tool != "tar" else ["/usr/bin/tar", "/bin/tar"]
    removed = await env.exec(["/bin/rm", "-f", *paths], user="root")
    assert removed.success, removed.stderr

    with pytest.raises(SandboxUnavailableError, match="required tools") as ex:
        await env.read_file(file, user="root")
    assert tool in str(ex.value)


@pytest.mark.slow
@skip_if_no_docker
async def test_docker_read_file_nonexecutable_execution_machinery(
    docker_environment: DockerSandboxEnvironment,
) -> None:
    env = docker_environment
    file = f"/tmp/inspect-read-dependency-{uuid4().hex}"
    await env.write_file(file, "exists")
    assert (await env.exec(["chmod", "000", "/usr/bin/timeout"])).success
    with pytest.raises(SandboxUnavailableError, match="required tools") as ex:
        await env.read_file(file)
    assert "permission denied" in str(ex.value).lower()


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize(
    "docker_environment",
    [
        {
            "services": {
                "default": {
                    "image": "aisiuk/inspect-tool-support",
                    "working_dir": "/tmp/removable-workdir",
                    "command": "tail -f /dev/null",
                    "init": True,
                    "network_mode": "none",
                    "stop_grace_period": "1s",
                }
            }
        }
    ],
    indirect=True,
)
async def test_docker_read_file_survives_removed_working_directory(
    docker_environment: DockerSandboxEnvironment,
) -> None:
    env = docker_environment
    file = "/tmp/read-file-public"
    await env.write_file(file, "public")
    assert (await env.exec(["chmod", "644", file])).success
    assert (await env.exec(["rm", "-rf", "/tmp/removable-workdir"], cwd="/")).success

    for user in [None, "65534", "root"]:
        assert await env.read_file(file, user=user) == "public"


@pytest.mark.slow
@skip_if_no_docker
async def test_docker_read_file_bounds_archive_stderr(
    docker_environment: DockerSandboxEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.util._sandbox import _privileged

    env = docker_environment
    root = f"/tmp/inspect-read-stderr-{uuid4().hex}"
    await env.write_file(
        f"{root}/tar",
        "#!/bin/sh\n/usr/bin/head -c 1048576 /dev/zero >&2\nprintf diagnostic-tail >&2\nexit 1\n",
    )
    assert (await env.exec(["chmod", "+x", f"{root}/tar"])).success
    monkeypatch.setattr(_privileged, "SYSTEM_PATH", root)

    with override_max_exec_output_size(1024):
        with pytest.raises(RuntimeError, match="diagnostic-tail") as ex:
            await env.read_file("/ignored")
    assert len(str(ex.value)) < 2048


@pytest.mark.slow
@skip_if_no_docker
async def test_docker_file_operations_reject_unknown_users(
    docker_environment: DockerSandboxEnvironment,
) -> None:
    env = docker_environment
    file = f"/tmp/inspect-unknown-user-{uuid4().hex}"
    await env.write_file(file, "original")
    for user in [
        "inspect-user-does-not-exist",
        "root:inspect-group-does-not-exist",
        "permission denied",
    ]:
        with pytest.raises(SandboxUserUnsupportedError):
            await env.read_file(file, user=user)
        with pytest.raises(SandboxUserUnsupportedError):
            await env.write_file(file, "changed", user=user)
        assert await env.read_file(file) == "original"


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize(
    "docker_environment",
    [
        {
            "services": {
                "default": {
                    "image": "aisiuk/inspect-tool-support",
                    "command": "tail -f /dev/null",
                    "init": True,
                    "network_mode": "none",
                    "stop_grace_period": "1s",
                    "environment": {"TAR_OPTIONS": "--gzip"},
                }
            }
        }
    ],
    indirect=True,
)
async def test_docker_read_file_ignores_image_tar_options(
    docker_environment: DockerSandboxEnvironment,
) -> None:
    env = docker_environment
    options = await env.exec(["/bin/sh", "-c", 'printf %s "$TAR_OPTIONS"'])
    assert options.stdout == "--gzip"
    payload = b"\xff\x00contents\r\n"
    for name in [
        "space name",
        "quote'\"name",
        "line\nbreak",
        "-leading",
        "$(touch SHOULD_NOT_EXIST)",
        "semi;colon",
        "unicode-\u96ea",
        "x" * 240,
    ]:
        file = f"/tmp/{name}"
        await env.write_file(file, payload)
        assert await env.read_file(file, text=False) == payload


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize(
    "docker_environment",
    [
        None,
        str(Path(__file__).parents[2] / "tools/test_sandbox_compose.yaml"),
        str(Path(__file__).parents[2] / "tools/test_sandbox_compose_alpine.yaml"),
    ],
    indirect=True,
    ids=["root", "nonroot", "alpine"],
)
async def test_docker_file_users_enforce_symlink_permissions(
    docker_environment: DockerSandboxEnvironment, tmp_path: Path
) -> None:
    env = docker_environment
    root = f"/tmp/inspect-file-users-{uuid4().hex}"
    private = f"{root}/private"
    shared = f"{root}/shared"
    secret = f"{private}/secret"
    setup = await env.exec(
        [
            "/bin/sh",
            "-c",
            'mkdir -p "$1/private" "$1/shared"; '
            'chmod 755 "$1"; chmod 700 "$1/private"; chmod 777 "$1/shared"; '
            'printf secret > "$1/private/secret"; chmod 600 "$1/private/secret"',
            "sh",
            root,
        ],
        user="root",
    )
    assert setup.success, setup.stderr
    try:
        planted = await env.exec(
            [
                "/bin/sh",
                "-c",
                'ln -s "$1" "$2/link"; ln -s "$3" "$2/dir"',
                "sh",
                secret,
                shared,
                private,
            ],
            user="65534",
        )
        assert planted.success, planted.stderr
        with pytest.raises(PermissionError):
            await env.read_file(f"{shared}/link", user="65534")
        with pytest.raises(PermissionError):
            await env.write_file(f"{shared}/link", "changed", user="65534")
        with pytest.raises(PermissionError):
            await env.write_file(f"{shared}/dir/new", b"changed", user="65534")
        assert await env.read_file(secret, user="root") == "secret"

        default_uid = await env.exec(["id", "-u"])
        if default_uid.stdout.strip() == "0":
            assert await env.read_file(f"{shared}/link") == "secret"
        else:
            with pytest.raises(PermissionError):
                await env.read_file(f"{shared}/link")

        # Checkpoint chunks stay private even when the container defaults to non-root.
        dest = tmp_path / "checkpoint"
        await copy_out(
            env,
            src=secret,
            chunk_path=f"{private}/chunk",
            size=6,
            dest=dest,
            max_bytes=100,
            label="checkpoint",
            chunk_size=100,
        )
        assert dest.read_bytes() == b"secret"
        await env.write_file(f"{shared}/owned/nested/file", b"\xff\r\n", user="65534")
        assert (
            await env.read_file(f"{shared}/owned/nested/file", False, user="65534")
            == b"\xff\r\n"
        )
        owner = await env.exec(["stat", "-c", "%u", f"{shared}/owned/nested/file"])
        assert owner.stdout.strip() == "65534"
    finally:
        await env.exec(["rm", "-rf", "--", root], user="root")


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize(
    "docker_environment",
    [None, str(Path(__file__).parents[2] / "tools/test_sandbox_compose_alpine.yaml")],
    indirect=True,
)
async def test_docker_read_cancellation_retains_container_timeout(
    docker_environment: DockerSandboxEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host cancellation retains Docker exec's in-container timeout fallback."""
    from inspect_ai.util._sandbox import _privileged

    env = docker_environment
    root = f"/tmp/inspect-read-cancel-{uuid4().hex}"
    await env.write_file(
        f"{root}/tar",
        f"#!/bin/sh\necho $$ > {root}/pid\nprintf ready\nexec /bin/sleep 600\n",
    )
    assert (await env.exec(["chmod", "+x", f"{root}/tar"])).success
    original_path = _privileged.SYSTEM_PATH
    original_reader = docker_module._read_archive
    started = anyio.Event()

    async def read_archive(
        stream: ByteReceiveStream, limit: int, original_file: str
    ) -> bytes:
        assert await stream.receive()
        started.set()
        await anyio.sleep_forever()
        return b""

    monkeypatch.setattr(_privileged, "SYSTEM_PATH", root)
    monkeypatch.setattr(compose_module, "_READ_FILE_TIMEOUT", 4)
    monkeypatch.setattr(docker_module, "_read_archive", read_archive)
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(env.read_file, "/ignored")
            with anyio.fail_after(10):
                await started.wait()
            tg.cancel_scope.cancel()
        with anyio.fail_after(10):
            while (
                await env.exec(
                    [
                        "/bin/sh",
                        "-c",
                        'read pid < "$1/pid"; kill -0 "$pid" 2>/dev/null',
                        "sh",
                        root,
                    ],
                    concurrency=False,
                )
            ).success:
                pass
    finally:
        monkeypatch.setattr(_privileged, "SYSTEM_PATH", original_path)
        monkeypatch.setattr(docker_module, "_read_archive", original_reader)
        await env.exec(["/bin/rm", "-rf", "--", root])


def _remove_host_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


@pytest.mark.slow
@skip_if_no_docker
async def test_docker_read_file_contains_untrusted_sources(
    docker_environment: DockerSandboxEnvironment,
) -> None:
    unique_name = f"inspect-read-file-{uuid4().hex}"
    container_root = f"/tmp/{unique_name}"
    host_escape = Path(tempfile.gettempdir()) / unique_name
    _remove_host_path(host_escape)

    try:
        mkdir = await docker_environment.exec(
            ["mkdir", "-p", f"{container_root}/child"]
        )
        assert mkdir.success
        await docker_environment.write_file(
            f"{container_root}/marker.txt", "sandbox-marker"
        )

        link_file = await docker_environment.exec(
            ["ln", "-s", "marker.txt", f"{container_root}/link-file"]
        )
        assert link_file.success
        link_directory = await docker_environment.exec(
            ["ln", "-s", "child", f"{container_root}/link-directory"]
        )
        assert link_directory.success
        fifo = await docker_environment.exec(["mkfifo", f"{container_root}/fifo"])
        assert fifo.success
        socket_path = f"{container_root}/socket"
        socket_script = (
            "import socket,time;"
            "sock=socket.socket(socket.AF_UNIX);"
            f"sock.bind({socket_path!r});"
            "sock.listen();"
            "time.sleep(600)"
        )
        socket = await docker_environment.exec(
            [
                "sh",
                "-c",
                f"python -c {shlex.quote(socket_script)} "
                f"</dev/null >{shlex.quote(f'{container_root}/socket.log')} 2>&1 & "
                f"while [ ! -S {shlex.quote(socket_path)} ]; do sleep 0.01; done",
            ],
            timeout=10,
        )
        assert socket.success

        assert (
            await docker_environment.read_file(f"{container_root}/marker.txt")
            == "sandbox-marker"
        )
        assert (
            await docker_environment.read_file(f"{container_root}/link-file")
            == "sandbox-marker"
        )

        with pytest.raises(IsADirectoryError):
            await docker_environment.read_file(f"{container_root}/child/..")
        assert not host_escape.exists()

        with pytest.raises(IsADirectoryError):
            await docker_environment.read_file(f"{container_root}/child")
        with pytest.raises(IsADirectoryError):
            await docker_environment.read_file(f"{container_root}/link-directory")

        with pytest.raises(OSError) as ex:
            await docker_environment.read_file(f"{container_root}/fifo")
        assert ex.value.errno == errno.EINVAL

        with pytest.raises(OSError) as ex:
            await docker_environment.read_file(socket_path)
        assert ex.value.errno == errno.EINVAL

        remove_test = await docker_environment.exec(
            ["sh", "-c", "rm -f /bin/test /usr/bin/test"]
        )
        assert remove_test.success
        assert (
            await docker_environment.read_file(f"{container_root}/marker.txt")
            == "sandbox-marker"
        )
        assert not host_escape.exists()
    finally:
        _remove_host_path(host_escape)


@pytest.mark.slow
@skip_if_no_docker
async def test_docker_read_file_stops_at_size_limit(
    docker_environment: DockerSandboxEnvironment,
) -> None:
    limit = 1024 * 1024
    root = f"/tmp/inspect-read-limit-{uuid4().hex}"
    setup_script = (
        "import os;"
        f"root={root!r};"
        "os.makedirs(root + '/directory');"
        f"open(root + '/at-limit', 'wb').write(b'x' * {limit});"
        "open(root + '/over-limit', 'wb').truncate(64 * 1024 * 1024);"
        f"open(root + '/directory/child', 'wb').write(b'x' * {2 * limit})"
    )
    setup = await docker_environment.exec(["python", "-c", setup_script])
    assert setup.success, setup.stderr

    with override_max_read_file_size(limit):
        at_limit = await docker_environment.read_file(f"{root}/at-limit", text=False)
        assert at_limit == b"x" * limit

        with pytest.raises(OutputLimitExceededError):
            await docker_environment.read_file(f"{root}/over-limit")

        with pytest.raises(IsADirectoryError):
            await docker_environment.read_file(f"{root}/directory")

    after = await docker_environment.exec(["true"], timeout=60)
    assert after.success
