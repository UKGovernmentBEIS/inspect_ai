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

import pytest
from anyio.abc import ByteReceiveStream
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util._sandbox.docker import docker as docker_module
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.docker.util import ComposeProject
from inspect_ai.util._sandbox.limits import (
    OutputLimitExceededError,
    override_max_read_file_size,
)
from inspect_ai.util._subprocess import StdoutReader


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
    """Fake `compose_cp_archive` that streams `archive` to its reader."""

    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(archive), 4096):
            yield archive[start : start + 4096]

    async def copy(
        src: str, project: ComposeProject, read_archive: StdoutReader
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
    monkeypatch.setattr(docker_module, "compose_cp_archive", copy_mock)

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
    monkeypatch.setattr(docker_module, "compose_cp_archive", copy_mock)

    assert await environment.read_file("/sandbox/source.txt", text=False) == b"hi\r\n"
    assert await environment.read_file("/sandbox/source.txt") == "hi\r\n"

    assert copy_mock.await_args is not None
    assert copy_mock.await_args.kwargs["src"] == "default:/sandbox/source.txt"
    assert copy_mock.await_args.kwargs["project"] is environment._project
    exec_mock.assert_not_awaited()


async def test_read_file_allows_empty_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    copy_mock = _copy_returning(_archive(("empty", tarfile.REGTYPE, b"")))
    monkeypatch.setattr(docker_module, "compose_cp_archive", copy_mock)

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
    monkeypatch.setattr(docker_module, "compose_cp_archive", copy_mock)

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
    monkeypatch.setattr(docker_module, "compose_cp_archive", _copy_returning(archive))

    with pytest.raises(OSError) as ex:
        await environment.read_file("source")

    assert ex.value.errno == errno.EINVAL
    assert ex.value.filename == "source"


async def test_read_file_rejects_file_without_owner_read_permission(
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
        docker_module, "compose_cp_archive", _copy_returning(buffer.getvalue())
    )

    with pytest.raises(PermissionError) as ex:
        await environment.read_file("unreadable.txt")

    assert ex.value.errno == errno.EACCES
    assert ex.value.filename == "unreadable.txt"


async def test_read_file_rejects_invalid_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    monkeypatch.setattr(
        docker_module, "compose_cp_archive", _copy_returning(b"not a tar archive")
    )

    with pytest.raises(RuntimeError, match="invalid archive"):
        await environment.read_file("source")


async def test_read_file_enforces_size_limit_on_archived_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()

    with override_max_read_file_size(10):
        over = _copy_returning(_archive(("big", tarfile.REGTYPE, b"x" * 11)))
        monkeypatch.setattr(docker_module, "compose_cp_archive", over)
        with pytest.raises(OutputLimitExceededError):
            await environment.read_file("big")

        at = _copy_returning(_archive(("big", tarfile.REGTYPE, b"x" * 10)))
        monkeypatch.setattr(docker_module, "compose_cp_archive", at)
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
    monkeypatch.setattr(docker_module, "compose_cp_archive", _copy_returning(archive))

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
    monkeypatch.setattr(docker_module, "compose_cp_archive", copy_mock)

    with pytest.raises(FileNotFoundError) as ex:
        await environment.read_file("missing")

    assert ex.value.filename == "missing"
    copy_mock.assert_awaited_once()


@pytest.fixture
async def docker_environment(
    request: pytest.FixtureRequest,
) -> AsyncIterator[DockerSandboxEnvironment]:
    task_name = f"{__name__}_{request.node.name}"
    await DockerSandboxEnvironment.task_init(task_name=task_name, config=None)
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
        await DockerSandboxEnvironment.task_cleanup(
            task_name=task_name, config=None, cleanup=True
        )


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
