import errno
import shutil
import stat
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util._sandbox.docker import docker as docker_module
from inspect_ai.util._sandbox.docker.docker import (
    DockerSandboxEnvironment,
    _validate_staged_read_file,
)
from inspect_ai.util._sandbox.docker.util import ComposeProject
from inspect_ai.util._subprocess import ExecResult


def _environment() -> DockerSandboxEnvironment:
    project = ComposeProject(
        name="test",
        config=None,
        sample_id=None,
        epoch=None,
        env=None,
    )
    return DockerSandboxEnvironment("default", project, "/work")


def _exec_result(success: bool) -> ExecResult[str]:
    return ExecResult(
        success=success,
        returncode=0 if success else 1,
        stdout="",
        stderr="",
    )


@pytest.mark.parametrize("file", [".", "./", "..", "../", "dir/.", "dir/../"])
async def test_read_file_rejects_directory_alias_before_copy(
    file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment()
    exec_mock = AsyncMock()
    copy_mock = AsyncMock()
    monkeypatch.setattr(environment, "exec", exec_mock)
    monkeypatch.setattr(docker_module, "compose_cp", copy_mock)

    with pytest.raises(IsADirectoryError) as ex:
        await environment.read_file(file)

    assert file in str(ex.value)
    exec_mock.assert_not_awaited()
    copy_mock.assert_not_awaited()


async def test_read_file_uses_precreated_random_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    exec_mock = AsyncMock(return_value=_exec_result(True))
    monkeypatch.setattr(environment, "exec", exec_mock)

    async def copy_file(
        src: str,
        dest: str,
        project: ComposeProject,
        cwd: str | Path | None = None,
        output_limit: int | None = None,
    ) -> None:
        assert src == "default:/sandbox/source.txt"
        assert project is environment._project
        assert cwd is not None
        assert output_limit is not None
        assert dest not in (".", "..")
        assert "/" not in dest
        assert "\\" not in dest

        staged_path = Path(cwd) / dest
        assert staged_path.parent.resolve(strict=True) == Path(cwd).resolve(strict=True)
        assert stat.S_ISREG(staged_path.lstat().st_mode)
        staged_path.write_bytes(b"hello\r\n")

    monkeypatch.setattr(docker_module, "compose_cp", copy_file)

    result = await environment.read_file("/sandbox/source.txt", text=False)

    assert result == b"hello\r\n"
    exec_mock.assert_awaited_once_with(["test", "-f", "/sandbox/source.txt"])


async def test_read_file_rejects_directory_source_before_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    exec_mock = AsyncMock(side_effect=[_exec_result(False), _exec_result(True)])
    copy_mock = AsyncMock()
    monkeypatch.setattr(environment, "exec", exec_mock)
    monkeypatch.setattr(docker_module, "compose_cp", copy_mock)

    with pytest.raises(IsADirectoryError) as ex:
        await environment.read_file("directory")

    assert "directory" in str(ex.value)
    copy_mock.assert_not_awaited()


async def test_read_file_rejects_special_source_before_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    exec_mock = AsyncMock(
        side_effect=[
            _exec_result(False),
            _exec_result(False),
            _exec_result(True),
        ]
    )
    copy_mock = AsyncMock()
    monkeypatch.setattr(environment, "exec", exec_mock)
    monkeypatch.setattr(docker_module, "compose_cp", copy_mock)

    with pytest.raises(OSError) as ex:
        await environment.read_file("special")

    assert ex.value.errno == errno.EINVAL
    assert "special" in str(ex.value)
    copy_mock.assert_not_awaited()


async def test_read_file_preserves_missing_file_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    exec_mock = AsyncMock(
        side_effect=[
            _exec_result(False),
            _exec_result(False),
            _exec_result(False),
        ]
    )
    copy_mock = AsyncMock(
        side_effect=RuntimeError("Could not find the file in the container")
    )
    monkeypatch.setattr(environment, "exec", exec_mock)
    monkeypatch.setattr(docker_module, "compose_cp", copy_mock)

    with pytest.raises(FileNotFoundError) as ex:
        await environment.read_file("missing")

    assert ex.value.filename == "missing"
    copy_mock.assert_awaited_once()


async def test_read_file_rejects_non_regular_copy_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    monkeypatch.setattr(environment, "exec", AsyncMock(return_value=_exec_result(True)))

    async def copy_directory(
        src: str,
        dest: str,
        project: ComposeProject,
        cwd: str | Path | None = None,
        output_limit: int | None = None,
    ) -> None:
        assert cwd is not None
        staged_path = Path(cwd) / dest
        staged_path.unlink()
        staged_path.mkdir()

    monkeypatch.setattr(docker_module, "compose_cp", copy_directory)

    with pytest.raises(OSError) as ex:
        await environment.read_file("/sandbox/source.txt")

    assert ex.value.errno == errno.EINVAL
    assert ex.value.filename == "/sandbox/source.txt"


async def test_read_file_reports_original_path_for_unreadable_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    monkeypatch.setattr(environment, "exec", AsyncMock(return_value=_exec_result(True)))

    async def copy_file(
        src: str,
        dest: str,
        project: ComposeProject,
        cwd: str | Path | None = None,
        output_limit: int | None = None,
    ) -> None:
        assert cwd is not None
        (Path(cwd) / dest).write_text("secret")

    def permission_denied(*args: object, **kwargs: object) -> None:
        raise PermissionError(errno.EACCES, "Permission denied.", str(args[0]))

    monkeypatch.setattr(docker_module, "compose_cp", copy_file)
    monkeypatch.setattr("builtins.open", permission_denied)

    with pytest.raises(PermissionError) as ex:
        await environment.read_file("unreadable.txt")

    assert ex.value.errno == errno.EACCES
    assert ex.value.filename == "unreadable.txt"


def test_validate_staged_read_file_rejects_outside_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    temp_root = tmp_path / "staging"
    temp_root.mkdir()
    staged_path = temp_root / "read-test"

    try:
        staged_path.symlink_to(outside)
    except OSError:
        pytest.skip("Host does not permit creating symlinks")

    with pytest.raises(OSError) as ex:
        _validate_staged_read_file(temp_root.resolve(), staged_path, "source.txt")

    assert ex.value.errno == errno.EINVAL
    assert outside.read_text() == "outside"


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


@skip_if_no_docker
@pytest.mark.slow
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
        assert not host_escape.exists()
    finally:
        _remove_host_path(host_escape)
