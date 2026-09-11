"""Conformance tests for the guest-side verified-directory helper.

The server state directory and the chunked-response directories share this one
helper, so its contract is tested here once: creation with an exact mode, reuse
of a correct directory, repair of an owned directory, and refusal of anything
planted at the path.
"""

import os
import re
import stat
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from inspect_sandbox_tools._util.framework_directory import open_framework_directory

KIND = "Test directory"


def _open(path: Path, **overrides: Any) -> int:
    options: dict[str, Any] = {
        "kind": KIND,
        "owners": (os.geteuid(),),
        "mode": 0o700,
        "create": True,
    }
    options.update(overrides)
    return open_framework_directory(path, **options)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _fake_stat(path: Path, *, uid: int, mode: int) -> os.stat_result:
    values = list(path.lstat())
    values[0] = stat.S_IFDIR | mode
    values[4] = uid
    return os.stat_result(values)


@pytest.fixture
def restrictive_umask(tmp_path: Path) -> Generator[int, None, None]:
    """Mask every permission bit, as a hostile inherited umask would."""
    old_umask = os.umask(0o777)
    try:
        yield 0o777
    finally:
        os.umask(old_umask)


@pytest.mark.parametrize("mode", [0o700, 0o1733])
def test_creates_directory_with_exact_mode_despite_umask(
    tmp_path: Path, restrictive_umask: int, mode: int
) -> None:
    directory = tmp_path / "dir"

    fd = _open(directory, mode=mode)

    try:
        info = os.fstat(fd)
        assert stat.S_ISDIR(info.st_mode)
        assert stat.S_IMODE(info.st_mode) == mode
        assert info.st_ino == directory.lstat().st_ino
    finally:
        os.close(fd)
    assert os.umask(restrictive_umask) == restrictive_umask


def test_reuses_correct_directory_and_repairs_owned_mode(tmp_path: Path) -> None:
    directory = tmp_path / "dir"
    directory.mkdir()
    (directory / "keep").write_text("x")
    os.chmod(directory, 0o755)

    os.close(_open(directory))
    os.close(_open(directory))

    assert _mode(directory) == 0o700
    assert (directory / "keep").read_text() == "x"


def test_create_false_requires_an_existing_directory(tmp_path: Path) -> None:
    directory = tmp_path / "dir"

    with pytest.raises(FileNotFoundError):
        _open(directory, create=False)
    assert not directory.exists()

    directory.mkdir()
    os.close(_open(directory, create=False))


def test_creation_failure_reports_the_directory_and_restores_umask(
    tmp_path: Path, restrictive_umask: int
) -> None:
    directory = tmp_path / "missing-parent" / "dir"

    with pytest.raises(RuntimeError, match=re.escape(f"{directory} cannot be created")):
        _open(directory)

    assert os.umask(restrictive_umask) == restrictive_umask


@pytest.mark.parametrize(
    "planted",
    ["symlink", "dangling_symlink", "file", "foreign_owner", "foreign_mode"],
)
def test_rejects_planted_entry_and_leaves_it_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, planted: str
) -> None:
    directory = tmp_path / "dir"
    target = tmp_path / "target"
    current_uid = os.geteuid()
    overrides: dict[str, Any] = {}
    if planted == "symlink":
        target.mkdir(mode=0o755)
        directory.symlink_to(target, target_is_directory=True)
        reason = "it is a symbolic link"
    elif planted == "dangling_symlink":
        directory.symlink_to(tmp_path / "missing")
        reason = "it is a symbolic link"
    elif planted == "file":
        directory.write_text("not a directory")
        reason = "it is not a directory"
    elif planted == "foreign_owner":
        directory.mkdir()
        os.chmod(directory, 0o755)
        overrides["owners"] = (current_uid + 1, current_uid + 2)
        reason = (
            f"it is owned by uid {current_uid}, "
            f"not uid {current_uid + 1} or uid {current_uid + 2}"
        )
    else:
        # Owned by an allowed uid that is not the caller: verified, never repaired.
        directory.mkdir()
        os.chmod(directory, 0o755)
        overrides["owners"] = (current_uid,)
        monkeypatch.setattr(os, "geteuid", lambda: current_uid + 1)
        reason = "it has mode 0755, not 0700"

    with pytest.raises(
        RuntimeError,
        match=re.escape(f"{KIND} {directory} cannot be trusted: {reason}"),
    ):
        _open(directory, **overrides)

    if planted == "symlink":
        assert directory.is_symlink() and _mode(target) == 0o755
    elif planted == "dangling_symlink":
        assert directory.is_symlink() and not directory.exists()
    elif planted == "file":
        assert directory.read_text() == "not a directory"
    else:
        assert _mode(directory) == 0o755


def test_owned_directory_that_cannot_be_opened_is_refused(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root is not subject to directory modes")
    directory = tmp_path / "dir"
    directory.mkdir()
    os.chmod(directory, 0o000)

    try:
        with pytest.raises(
            RuntimeError,
            match=f"owned by uid {os.geteuid()} with mode 0000 and cannot be opened",
        ):
            _open(directory)
        assert _mode(directory) == 0o000
    finally:
        os.chmod(directory, 0o700)


def test_entry_is_resolved_relative_to_the_parent_descriptor(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # Only the final component matters; the path's own parent is never walked.
        fd = _open(Path("/nonexistent/parent") / "child", dir_fd=parent_fd)
        os.close(fd)
        assert (parent / "child").is_dir() and _mode(parent / "child") == 0o700

        victim = tmp_path / "victim"
        victim.mkdir(mode=0o755)
        (parent / "link").symlink_to(victim, target_is_directory=True)
        with pytest.raises(RuntimeError, match="it is a symbolic link"):
            _open(parent / "link", dir_fd=parent_fd)
        assert _mode(victim) == 0o755
    finally:
        os.close(parent_fd)


def test_entry_replaced_after_creation_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory swapped for a symlink between mkdir and open is refused."""
    directory = tmp_path / "dir"
    victim = tmp_path / "victim"
    victim.mkdir(mode=0o755)
    real_mkdir = os.mkdir

    def mkdir_then_swap(
        path: Any, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        real_mkdir(path, mode, dir_fd=dir_fd)
        os.rmdir(path, dir_fd=dir_fd)
        os.symlink(victim, path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "mkdir", mkdir_then_swap)

    with pytest.raises(RuntimeError, match="it is a symbolic link"):
        _open(directory)

    assert directory.is_symlink() and _mode(victim) == 0o755


@pytest.mark.skipif(not hasattr(os, "O_PATH"), reason="O_PATH is Linux-only")
def test_shared_directory_without_read_permission_is_opened_with_o_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-owner may lack the read bit on a 1733 root; O_PATH still verifies it."""
    directory = tmp_path / "dir"
    directory.mkdir(mode=0o1733)
    real_open = os.open
    opens: list[int] = []

    def open_without_read_permission(
        path: Any, flags: int, *args: Any, **kwargs: Any
    ) -> int:
        opens.append(flags)
        if not flags & os.O_PATH:
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_without_read_permission)
    monkeypatch.setattr(
        os, "fstat", lambda _fd: _fake_stat(directory, uid=0, mode=0o1733)
    )
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    fd = _open(directory, owners=(0, 1000), mode=0o1733, shared=True)
    os.close(fd)
    assert len(opens) == 2 and opens[1] & os.O_PATH

    # A private directory gets no such fallback, and an owner who would have to
    # repair the mode cannot do so through O_PATH.
    with pytest.raises(RuntimeError, match="cannot be opened"):
        _open(directory, owners=(0, 1000), mode=0o1733)
    monkeypatch.setattr(
        os, "fstat", lambda _fd: _fake_stat(directory, uid=1000, mode=0o1700)
    )
    with pytest.raises(RuntimeError, match="with mode 1700 and cannot be opened"):
        _open(directory, owners=(0, 1000), mode=0o1733, shared=True)
