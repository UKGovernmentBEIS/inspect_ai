"""Host-side verification of sandbox egress tarballs (pure tar, no restic).

``_extract_verified`` unpacks a tarball whose bytes were produced *inside*
the sandbox onto the host. The archive is therefore untrusted — where the
sandbox default user is root, the agent controls it directly — so every
acceptance decision is made from host-side truth: members must be regular
files in the restic layout (``filter="data"`` beneath that rejects ``..``
traversal, absolute paths and outside-pointing links), must be exactly the
sandbox's diff list, may not replace files already in the destination,
must hash to their own names (restic's content addressing), and must stay
within the byte cap. A failure leaves the destination as it was found.
"""

from __future__ import annotations

import errno
import hashlib
import io
import json
import sqlite3
import tarfile
import tracemalloc
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import IO
from unittest.mock import patch

import anyio
import pytest

from inspect_ai.util._checkpoint._sandbox_restic.egress import (
    _MIN_SNAPSHOT_FILE_BYTES,
    EgressVerificationError,
    _build_validation_view,
    _check_index_containment,
    _extract_verified,
    _index_memo_path,
    _IndexMemo,
    _merge_into_repo,
    _parse_blob_listing,
    _publish_into,
    _remove_files,
    _validate_view,
    _verify_published,
)


def _blob(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _data_name(data: bytes) -> str:
    digest = _blob(data)
    return f"data/{digest[:2]}/{digest}"


def _file(name: str, data: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    return info, data


def _tar(tmp_path: Path, *members: tuple[tarfile.TarInfo, bytes | None]) -> Path:
    path = tmp_path / "egress.tar"
    with tarfile.open(path, mode="w") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return path


def _dest(tmp_path: Path) -> Path:
    dest = tmp_path / "dest"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _files(dest: Path) -> set[str]:
    return {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}


def _extract(
    tar_path: Path,
    dest: Path,
    new_files: Sequence[str],
    *,
    existing: Collection[str] = (),
    first_cycle: bool = False,
    max_bytes: int = 1 << 30,
) -> list[str]:
    result = _extract_verified(
        tar_path,
        str(dest),
        new_files=new_files,
        existing=existing,
        first_cycle=first_cycle,
        max_bytes=max_bytes,
        label="test egress",
    )
    return result.members


PACK = b"pack bytes " * 100
INDEX = b"index bytes"
SNAP = b"snapshot bytes, long enough to be a ciphertext"
PACK_NAME = _data_name(PACK)
INDEX_NAME = f"index/{_blob(INDEX)}"
SNAP_NAME = f"snapshots/{_blob(SNAP)}"


def test_extracts_content_addressed_members(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    tar = _tar(
        tmp_path,
        _file(PACK_NAME, PACK),
        _file(INDEX_NAME, INDEX),
        _file(SNAP_NAME, SNAP),
    )

    members = _extract(tar, dest, [PACK_NAME, INDEX_NAME, SNAP_NAME])

    assert members == sorted([PACK_NAME, INDEX_NAME, SNAP_NAME])
    assert _files(dest) == set(members)
    assert (dest / PACK_NAME).read_bytes() == PACK


def test_config_and_keys_accepted_only_on_first_cycle(tmp_path: Path) -> None:
    key = b"key file"
    key_name = f"keys/{_blob(key)}"
    config = b"restic config (not content-addressed)"

    dest = _dest(tmp_path)
    tar = _tar(tmp_path, _file("config", config), _file(key_name, key))
    assert _extract(tar, dest, ["config", key_name], first_cycle=True) == [
        "config",
        key_name,
    ]
    assert (dest / "config").read_bytes() == config

    later = _dest(tmp_path / "later")
    for name in ("config", key_name):
        with pytest.raises(EgressVerificationError, match="uninitialized"):
            _extract(tar, later, ["config", key_name], first_cycle=False)
    assert _files(later) == set()


def test_rejects_snapshot_file_shorter_than_a_ciphertext(tmp_path: Path) -> None:
    """A snapshot member below restic's nonce-plus-MAC size never reaches staging.

    Such a file can never load, and restic 0.18.1 panics on one shorter than
    its nonce instead of skipping it, which would wedge every later listing.
    """
    assert len(SNAP) >= _MIN_SNAPSHOT_FILE_BYTES
    short = b"x" * (_MIN_SNAPSHOT_FILE_BYTES - 1)
    name = f"snapshots/{_blob(short)}"
    dest = _dest(tmp_path)
    tar = _tar(tmp_path, _file(PACK_NAME, PACK), _file(name, short))
    with pytest.raises(EgressVerificationError, match="shorter than restic"):
        _extract(tar, dest, [PACK_NAME, name])
    assert _files(dest) == set()
    # A pack that short is fine: only snapshot files are floored.
    tiny_pack = b"p" * 4
    tiny_name = f"data/{_blob(tiny_pack)[:2]}/{_blob(tiny_pack)}"
    tar = _tar(tmp_path, _file(tiny_name, tiny_pack))
    assert _extract(tar, dest, [tiny_name]) == [tiny_name]


def test_verify_published_checks_each_written_path(tmp_path: Path) -> None:
    """After publish, every written file must be a regular file of the staged size."""
    staging = tmp_path / "staging"
    dest = _dest(tmp_path)
    for root in (staging, dest):
        (root / "data" / "aa").mkdir(parents=True)
        (root / "data" / "aa" / "x").write_bytes(b"pack")
        (root / "snapshots").mkdir()
        (root / "snapshots" / "s").write_bytes(b"snapshot bytes")
    written = ["data/aa/x", "snapshots/s"]
    _verify_published(str(dest), staging, written)
    (dest / "snapshots" / "s").write_bytes(b"short")
    with pytest.raises(RuntimeError, match="not the 14-byte regular file"):
        _verify_published(str(dest), staging, written)
    (dest / "snapshots" / "s").unlink()
    with pytest.raises(RuntimeError, match="missing"):
        _verify_published(str(dest), staging, written)
    (dest / "snapshots" / "s").mkdir()
    with pytest.raises(RuntimeError, match="regular file"):
        _verify_published(str(dest), staging, written)


def test_rejects_member_not_in_diff_list(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    tar = _tar(tmp_path, _file(PACK_NAME, PACK), _file(SNAP_NAME, SNAP))

    with pytest.raises(EgressVerificationError, match="not in the sandbox's diff list"):
        _extract(tar, dest, [PACK_NAME])
    assert _files(dest) == set()


def test_rejects_member_overwriting_existing_file(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    existing = dest / SNAP_NAME
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"committed history")
    tar = _tar(tmp_path, _file(PACK_NAME, PACK), _file(SNAP_NAME, SNAP))

    with pytest.raises(EgressVerificationError, match="would overwrite"):
        _extract(tar, dest, [PACK_NAME, SNAP_NAME], existing={SNAP_NAME})
    assert existing.read_bytes() == b"committed history"
    # The pack extracted before the offending member was rolled back.
    assert _files(dest) == {SNAP_NAME}


def test_identical_reship_of_existing_file_is_a_no_op(tmp_path: Path) -> None:
    """A re-ship after a failed phase-2 commit: same bytes, never rewritten."""
    dest = _dest(tmp_path)
    existing = dest / SNAP_NAME
    existing.parent.mkdir(parents=True)
    existing.write_bytes(SNAP)
    before = existing.stat().st_mtime_ns
    tar = _tar(tmp_path, _file(SNAP_NAME, SNAP), _file(PACK_NAME, PACK))

    result = _extract_verified(
        tar,
        str(dest),
        new_files=[SNAP_NAME, PACK_NAME],
        existing={SNAP_NAME},
        first_cycle=False,
        max_bytes=1 << 30,
        label="test egress",
    )

    assert result.members == sorted([SNAP_NAME, PACK_NAME])
    assert result.written == [PACK_NAME]
    assert existing.stat().st_mtime_ns == before


def test_rejects_reship_of_existing_file_with_different_content(
    tmp_path: Path,
) -> None:
    dest = _dest(tmp_path)
    existing = dest / SNAP_NAME
    existing.parent.mkdir(parents=True)
    existing.write_bytes(SNAP)
    tar = _tar(
        tmp_path, _file(SNAP_NAME, b"different bytes, long enough to be a ciphertext")
    )

    with pytest.raises(EgressVerificationError, match="different content"):
        _extract(tar, dest, [SNAP_NAME], existing={SNAP_NAME})
    assert existing.read_bytes() == SNAP


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/abs/escape",
        "locks/" + "a" * 64,
        "data/" + "a" * 64,  # missing shard dir
        "data/zz/" + "a" * 64,  # shard dir not the hash prefix
        "data/" + "a" * 2 + "/" + "b" * 64,  # shard dir mismatches hash
        "snapshots/not-a-hash",
        "snapshots/" + "A" * 64,  # uppercase hex
        "restic-config.json",
        "config/nested",
    ],
)
def test_rejects_names_outside_restic_layout(tmp_path: Path, name: str) -> None:
    dest = _dest(tmp_path)
    tar = _tar(tmp_path, _file(name, b"pwned"))

    with pytest.raises(EgressVerificationError):
        _extract(tar, dest, [name])
    assert _files(dest) == set()
    assert not (tmp_path / "escape").exists()
    assert not Path("/abs/escape").exists()


def test_rejects_symlink_and_directory_members(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    link = tarfile.TarInfo(name=SNAP_NAME)
    link.type = tarfile.SYMTYPE
    link.linkname = "../outside"
    with pytest.raises(EgressVerificationError):
        _extract(_tar(tmp_path, (link, None)), dest, [SNAP_NAME])

    directory = tarfile.TarInfo(name="index/" + "c" * 64)
    directory.type = tarfile.DIRTYPE
    with pytest.raises(EgressVerificationError, match="not a regular file"):
        _extract(_tar(tmp_path, (directory, None)), dest, [directory.name])
    assert _files(dest) == set()
    assert not (tmp_path / "outside").exists()


def test_rejects_content_not_hashing_to_name_and_rolls_back(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    forged = f"snapshots/{'f' * 64}"
    tar = _tar(tmp_path, _file(PACK_NAME, PACK), _file(forged, SNAP))

    with pytest.raises(EgressVerificationError, match="not to its name"):
        _extract(tar, dest, [PACK_NAME, forged])
    # Neither the forged member nor the earlier (valid) one survives.
    assert _files(dest) == set()
    assert not list(dest.rglob("*.partial"))


def test_rejects_member_set_smaller_than_diff_list(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    tar = _tar(tmp_path, _file(PACK_NAME, PACK))

    with pytest.raises(EgressVerificationError, match="absent from the tarball"):
        _extract(tar, dest, [PACK_NAME, SNAP_NAME])
    assert _files(dest) == set()


def test_rejects_duplicate_and_surplus_members(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    duplicated = _tar(tmp_path, _file(SNAP_NAME, SNAP), _file(SNAP_NAME, SNAP))
    with pytest.raises(EgressVerificationError, match="more than once"):
        _extract(duplicated, dest, [SNAP_NAME])

    surplus = _tar(tmp_path, _file(SNAP_NAME, SNAP), _file(PACK_NAME, PACK))
    with pytest.raises(EgressVerificationError, match="not in the sandbox's diff"):
        _extract(surplus, dest, [SNAP_NAME])
    assert _files(dest) == set()


def test_config_reship_accepted_only_when_identical(tmp_path: Path) -> None:
    """``config`` is not content-addressed: a re-ship must match byte-for-byte."""
    dest = _dest(tmp_path)
    (dest / "config").write_bytes(b"repo config")

    identical = _tar(tmp_path, _file("config", b"repo config"))
    result = _extract_verified(
        identical,
        str(dest),
        new_files=["config"],
        existing={"config"},
        first_cycle=False,
        max_bytes=1 << 30,
        label="test egress",
    )
    assert result.members == ["config"] and result.written == []

    different = _tar(tmp_path, _file("config", b"attacker config"))
    with pytest.raises(EgressVerificationError, match="different content"):
        _extract(different, dest, ["config"], existing={"config"})
    assert (dest / "config").read_bytes() == b"repo config"


def test_truncated_member_data_is_a_verification_error(tmp_path: Path) -> None:
    """A tar cut inside a member's data (headers intact) is 'unreadable', not a raw ReadError."""
    dest = _dest(tmp_path)
    tar = _tar(tmp_path, _file(PACK_NAME, PACK), _file(INDEX_NAME, INDEX))
    data = tar.read_bytes()
    tar.write_bytes(data[: 512 + len(PACK) // 2])

    with pytest.raises(EgressVerificationError, match="unreadable tarball"):
        _extract(tar, dest, [PACK_NAME, INDEX_NAME])
    assert _files(dest) == set()


def test_rejects_extraction_exceeding_byte_cap(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    tar = _tar(tmp_path, _file(SNAP_NAME, SNAP), _file(PACK_NAME, PACK))

    with pytest.raises(EgressVerificationError, match="max_sandbox_snapshot_bytes"):
        _extract(tar, dest, [SNAP_NAME, PACK_NAME], max_bytes=len(SNAP) + 10)
    assert _files(dest) == set()
    assert not list(dest.rglob("*.partial"))


@pytest.mark.parametrize(
    "kind",
    [
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.SOLARIS_XHDTYPE,
    ],
)
def test_rejects_oversized_metadata_before_allocating(
    tmp_path: Path, kind: bytes
) -> None:
    header = tarfile.TarInfo("metadata")
    header.type = kind
    header.size = 64 * 1024 * 1024
    path = tmp_path / "egress.tar"
    path.write_bytes(header.tobuf() + bytes(1024))
    dest = _dest(tmp_path)
    tracemalloc.start()
    try:
        with pytest.raises(EgressVerificationError, match="tar metadata"):
            _extract(path, dest, [SNAP_NAME], max_bytes=path.stat().st_size)
        assert tracemalloc.get_traced_memory()[1] < 8 * 1024 * 1024
    finally:
        tracemalloc.stop()
    assert _files(dest) == set()


def test_rejects_chained_metadata_and_rolls_back(tmp_path: Path) -> None:
    header = tarfile.TarInfo("metadata")
    header.type = tarfile.XGLTYPE
    header.size = 0
    member, data = _file(PACK_NAME, PACK)
    path = tmp_path / "egress.tar"
    path.write_bytes(
        member.tobuf()
        + data
        + bytes(-len(data) % 512)
        + header.tobuf() * 256
        + bytes(1024)
    )
    dest = _dest(tmp_path)
    with pytest.raises(EgressVerificationError, match="tar metadata"):
        _extract(path, dest, [PACK_NAME])
    assert _files(dest) == set()


@pytest.mark.parametrize(
    "format", [tarfile.USTAR_FORMAT, tarfile.GNU_FORMAT, tarfile.PAX_FORMAT]
)
def test_metadata_budget_preserves_tar_formats(tmp_path: Path, format: int) -> None:
    path = tmp_path / "egress.tar"
    data = b"x" * (2 * 1024 * 1024)
    name = _data_name(data)
    member, _ = _file(name, data)
    if format == tarfile.PAX_FORMAT:
        member.pax_headers = {"mtime": "1234567890.123456789"}
    with tarfile.open(path, "w", format=format) as archive:
        archive.addfile(member, io.BytesIO(data))
        index, _ = _file(INDEX_NAME, INDEX)
        archive.addfile(index, io.BytesIO(INDEX))
    dest = _dest(tmp_path)
    assert _extract(path, dest, [name, INDEX_NAME]) == sorted([name, INDEX_NAME])
    assert (dest / name).read_bytes() == data


def test_rejects_oversized_sparse_metadata(tmp_path: Path) -> None:
    data = b"1000000\n" + b"1\n" * 40000
    member, _ = _file(PACK_NAME, data)
    member.pax_headers = {
        "GNU.sparse.major": "1",
        "GNU.sparse.minor": "0",
        "GNU.sparse.realsize": "0",
        "GNU.sparse.name": PACK_NAME,
    }
    path = tmp_path / "egress.tar"
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as archive:
        archive.addfile(member, io.BytesIO(data))
    dest = _dest(tmp_path)
    with pytest.raises(EgressVerificationError, match="tar metadata"):
        _extract(path, dest, [PACK_NAME])
    assert _files(dest) == set()


def test_remove_files_unwinds_last_written_first(tmp_path: Path) -> None:
    """Rollback removes in reverse write order.

    A kill mid-rollback then never leaves a snapshot without its packs or
    a ``config`` without its key.
    """
    names = ["keys/k", "config", "data/ab/p", "index/i", "snapshots/s"]
    for name in names:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x")
    removed: list[str] = []
    real_unlink = Path.unlink

    def spy(self: Path, missing_ok: bool = False) -> None:
        removed.append(self.relative_to(tmp_path).as_posix())
        real_unlink(self, missing_ok=missing_ok)

    with patch.object(Path, "unlink", spy):
        _remove_files(str(tmp_path), names)

    assert removed == list(reversed(names))
    assert not any((tmp_path / name).exists() for name in names)


def _stage(staging: Path, names: Sequence[str]) -> None:
    for name in names:
        (staging / name).parent.mkdir(parents=True, exist_ok=True)
        (staging / name).write_bytes(name.encode())


def test_merge_into_repo_links_in_layout_order(tmp_path: Path) -> None:
    """Merge links keys, config, packs, indexes, then snapshots.

    The order keeps the accepted repo valid at every prefix under a hard
    kill: a snapshot never lands before the index and packs it references,
    and ``config`` never before its key. The merge sorts internally, so a
    tarball's member order cannot subvert it.
    """
    staging = tmp_path / "staging"
    dest = tmp_path / "dest"
    # Deliberately reversed input order to prove the merge re-sorts.
    written = ["snapshots/s", "index/i", "data/ab/p", "config", "keys/k"]
    _stage(staging, written)
    linked: list[str] = []
    real_link = __import__("os").link

    def spy(src: str, dst: str) -> None:
        linked.append(Path(dst).relative_to(dest).as_posix())
        real_link(src, dst)

    with patch("inspect_ai.util._checkpoint._sandbox_restic.egress.os.link", new=spy):
        _merge_into_repo(str(dest), staging, written)

    assert linked == ["keys/k", "config", "data/ab/p", "index/i", "snapshots/s"]
    assert {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()} == {
        "keys/k",
        "config",
        "data/ab/p",
        "index/i",
        "snapshots/s",
    }


def test_merge_into_repo_unwinds_on_failure(tmp_path: Path) -> None:
    """A merge that fails part-way removes its own files, last first."""
    staging = tmp_path / "staging"
    dest = tmp_path / "dest"
    written = ["data/ab/p", "index/i", "snapshots/s"]
    _stage(staging, written)
    real_publish = _publish_into

    def failing(src: Path, dst: Path) -> None:
        if dst.name == "i":
            raise OSError("disk full")
        real_publish(src, dst)

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress._publish_into", new=failing
    ):
        with pytest.raises(OSError, match="disk full"):
            _merge_into_repo(str(dest), staging, written)

    # The one pack published before the failure is removed again.
    assert not any(p.is_file() for p in dest.rglob("*"))


def test_merge_into_repo_never_overwrites_an_accepted_file(tmp_path: Path) -> None:
    """A collision with an existing accepted file is an error, not a clobber."""
    staging = tmp_path / "staging"
    dest = tmp_path / "dest"
    name = f"data/ab/{hashlib.sha256(b'x').hexdigest()}"
    _stage(staging, [name])
    (dest / name).parent.mkdir(parents=True, exist_ok=True)
    (dest / name).write_bytes(b"accepted bytes")

    with pytest.raises(FileExistsError):
        _merge_into_repo(str(dest), staging, [name])

    # The accepted file is untouched.
    assert (dest / name).read_bytes() == b"accepted bytes"


def _no_link(src: object, dst: object, *args: object, **kwargs: object) -> None:
    """Stand in for ``os.link`` on a filesystem without hard links (exFAT, some CIFS/NFS)."""
    raise OSError(errno.EPERM, "Operation not permitted (no hard links)")


_LINK = "inspect_ai.util._checkpoint._sandbox_restic.egress.os.link"


def test_merge_into_repo_copies_when_hard_links_unsupported(tmp_path: Path) -> None:
    """Without hard links the merge publishes by copy, atomically, in order.

    Each file is copied to a ``.partial`` sibling and renamed into place, so
    the final name only ever holds a complete file; nothing partial is left
    behind and the content matches the staged bytes.
    """
    staging = tmp_path / "staging"
    dest = tmp_path / "dest"
    written = ["snapshots/s", "index/i", "data/ab/p", "config", "keys/k"]
    _stage(staging, written)

    with patch(_LINK, new=_no_link):
        _merge_into_repo(str(dest), staging, written)

    for name in written:
        assert (dest / name).read_bytes() == name.encode()
        assert (dest / name).stat().st_nlink == 1  # a copy, not a link
    assert not list(dest.rglob("*.partial"))


def test_publish_copy_fallback_never_overwrites_an_accepted_file(
    tmp_path: Path,
) -> None:
    """The copy path keeps the no-overwrite rule a hard link gives for free."""
    staging = tmp_path / "staging"
    dest = tmp_path / "dest"
    name = f"data/ab/{hashlib.sha256(b'x').hexdigest()}"
    _stage(staging, [name])
    (dest / name).parent.mkdir(parents=True, exist_ok=True)
    (dest / name).write_bytes(b"accepted bytes")

    with patch(_LINK, new=_no_link):
        with pytest.raises(FileExistsError):
            _publish_into(staging / name, dest / name)

    assert (dest / name).read_bytes() == b"accepted bytes"
    assert not list(dest.rglob("*.partial"))


async def test_build_validation_view_copies_when_hard_links_unsupported(
    tmp_path: Path,
) -> None:
    """The throwaway view is built by copying where hard links are refused."""
    accepted = tmp_path / "accepted"
    staging = tmp_path / "staging"
    view = tmp_path / "view"
    _stage(accepted, ["config", "data/ab/old"])
    _stage(staging, ["data/cd/new", "index/i"])

    with patch(_LINK, new=_no_link):
        await _build_validation_view(
            view,
            existing_repo=str(accepted),
            existing=["config", "data/ab/old"],
            staging=staging,
            written=["data/cd/new", "index/i"],
        )

    assert {p.relative_to(view).as_posix() for p in view.rglob("*") if p.is_file()} == {
        "config",
        "data/ab/old",
        "data/cd/new",
        "index/i",
    }
    assert (view / "data/ab/old").read_bytes() == b"data/ab/old"
    assert (view / "data/ab/old").stat().st_nlink == 1


async def test_build_validation_view_copy_yields_within_a_large_file(
    tmp_path: Path,
) -> None:
    """A cancelled copy-mode view build stops between blocks of one file.

    Without hard links the view is a copy of the whole accepted repo, and a
    single staged file can be as large as the transfer cap, so a whole-file
    copy in one worker-thread call would make cancellation wait for it. The
    copy therefore proceeds ``_VIEW_COPY_BLOCK`` bytes per call. Here one
    32 MiB file is copied in 1 MiB blocks slowed to ~20 ms each; the cancel
    lands after ~2-3 blocks and the build returns within one block, leaving
    the file only partly copied.
    """
    import time

    import inspect_ai.util._checkpoint._sandbox_restic.egress as egress_mod

    accepted = tmp_path / "accepted"
    name = "data/ab/big"
    (accepted / name).parent.mkdir(parents=True)
    size = 32 * 1024 * 1024
    (accepted / name).write_bytes(b"x" * size)
    view = tmp_path / "view"
    real_read = egress_mod._read_block

    def slow_read(f: IO[bytes], n: int) -> bytes:
        time.sleep(0.02)
        return real_read(f, n)

    started = anyio.Event()

    async def build() -> None:
        started.set()
        await _build_validation_view(
            view,
            existing_repo=str(accepted),
            existing=[name],
            staging=tmp_path / "staging",
            written=[],
        )

    with (
        patch(_LINK, new=_no_link),
        patch.object(egress_mod, "_VIEW_COPY_BLOCK", 1024 * 1024),
        patch.object(egress_mod, "_read_block", slow_read),
    ):
        async with anyio.create_task_group() as tg:
            tg.start_soon(build)
            await started.wait()
            await anyio.sleep(0.05)
            t0 = time.perf_counter()
            tg.cancel_scope.cancel()
        waited = time.perf_counter() - t0

    copied = (view / name).stat().st_size
    assert 0 < copied < size, copied  # stopped part-way through the file
    assert waited < 0.2  # one block, not the whole 0.64 s file


async def test_build_validation_view_links_yield_between_batches(
    tmp_path: Path,
) -> None:
    """A cancelled link-mode view build stops between batches of files.

    Many tiny files must not turn one worker-thread call into a long
    uninterruptible run: links are attempted ``_VIEW_LINK_BATCH`` per call.
    Here 1000 files link at ~1 ms each in batches of 50; the cancel lands
    early and the build returns within one batch, most files unlinked.
    """
    import os
    import time

    import inspect_ai.util._checkpoint._sandbox_restic.egress as egress_mod

    accepted = tmp_path / "accepted"
    files = [f"data/ab/{i:04d}" for i in range(1000)]
    (accepted / "data/ab").mkdir(parents=True)
    for name in files:
        (accepted / name).write_bytes(b"x")
    view = tmp_path / "view"
    real_link = os.link

    def slow_link(src: str, dst: str) -> None:
        time.sleep(0.001)
        real_link(src, dst)

    started = anyio.Event()

    async def build() -> None:
        started.set()
        await _build_validation_view(
            view,
            existing_repo=str(accepted),
            existing=files,
            staging=tmp_path / "staging",
            written=[],
        )

    with (
        patch(_LINK, new=slow_link),
        patch.object(egress_mod, "_VIEW_LINK_BATCH", 50),
    ):
        async with anyio.create_task_group() as tg:
            tg.start_soon(build)
            await started.wait()
            await anyio.sleep(0.03)
            t0 = time.perf_counter()
            tg.cancel_scope.cancel()
        waited = time.perf_counter() - t0

    linked = sum(1 for p in view.rglob("*") if p.is_file())
    assert 0 < linked < len(files), linked  # stopped at a batch edge
    assert waited < 0.2  # one batch (~50 ms), not the whole second


async def test_build_validation_view_enumerates_lazily_and_cancels_early(
    tmp_path: Path,
) -> None:
    """The builder never walks the whole file list before its first checkpoint.

    A repository can hold hundreds of thousands of hash-named files (the
    transfer cap admits that many tiny ones per fire, and history has no
    total cap), so materialising or sorting every path up front would make a
    cancellation wait on file count before any batch ran. The builder pulls
    ``(src, dst)`` pairs one ``_VIEW_LINK_BATCH``-sized slice at a time. Here
    the file list counts how many names it has yielded and the (no-op) batch
    linker signals when the first batch is submitted; the test cancels on
    that signal — no sleeping — and asserts only a slice or two of the
    100,000 names was ever enumerated.
    """
    import threading
    from collections.abc import Iterator

    import inspect_ai.util._checkpoint._sandbox_restic.egress as egress_mod

    total = 100_000
    names = [f"data/{i & 255:02x}/{i:064x}" for i in range(total)]

    class Counting:
        """A Collection[str] that records how far it has been iterated."""

        def __init__(self) -> None:
            self.consumed = 0

        def __len__(self) -> int:
            return total

        def __contains__(self, item: object) -> bool:
            return item in names

        def __iter__(self) -> Iterator[str]:
            for name in names:
                self.consumed += 1
                yield name

    existing = Counting()
    first_batch = threading.Event()
    batches: list[int] = []

    def no_op_batch(pairs: list[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
        batches.append(len(pairs))
        first_batch.set()
        return []

    async def build() -> None:
        await _build_validation_view(
            tmp_path / "view",
            existing_repo=str(tmp_path / "accepted"),
            existing=existing,
            staging=tmp_path / "staging",
            written=[],
        )

    with patch.object(egress_mod, "_link_view_batch", no_op_batch):
        async with anyio.create_task_group() as tg:
            tg.start_soon(build)
            await anyio.to_thread.run_sync(first_batch.wait)
            tg.cancel_scope.cancel()

    assert batches and max(batches) <= egress_mod._VIEW_LINK_BATCH
    # Lazy: at most the batches that ran plus one slice being prepared.
    assert existing.consumed <= (len(batches) + 1) * egress_mod._VIEW_LINK_BATCH
    assert existing.consumed < total


# --- index containment and the index memo -------------------------------


def test_index_containment_rejects_remapped_blob() -> None:
    """A new index may not locate a blob an accepted index already locates.

    There is no pack rule any more (a new index may point its own new blobs
    at any pack; only entries for accepted blob ids reach back), so the
    former "own packs and unindexed residue" and "pack outside the transfer"
    cases are gone with it.
    """
    coverage = {"i1": {"data:new", "data:old", "tree:t"}}
    _check_index_containment(coverage, accepted_blobs=set(), label="t")
    with pytest.raises(EgressVerificationError, match="already locates"):
        _check_index_containment(coverage, accepted_blobs={"data:old"}, label="t")
    # Keys are type:id — restic looks blobs up by (type, id), so the same
    # hash as a tree and as a data blob are different lookups.
    _check_index_containment(coverage, accepted_blobs={"data:t"}, label="t")


_HEX_A = "a" * 64
_HEX_B = "b" * 64


def test_parse_blob_listing_normalises_restic_output() -> None:
    """``list blobs`` lines become lowercase ``type:id`` keys, deduplicated.

    The host normalises rather than validates: restic already loaded the
    index. Only a line restic would never print for a loaded index rejects.
    """
    raw = (
        f"data {_HEX_A}\ntree {_HEX_B}\ndata {_HEX_A.upper()}\n\ntree {_HEX_B}\n"
    ).encode()
    assert _parse_blob_listing(raw, label="t") == {f"data:{_HEX_A}", f"tree:{_HEX_B}"}
    assert _parse_blob_listing(b"", label="t") == set()
    for bad in (
        b"data " + b"a" * 63,
        b"blob " + b"a" * 64,
        b"data  " + b"a" * 64,
        b"x",
    ):
        with pytest.raises(EgressVerificationError, match="unexpected line"):
            _parse_blob_listing(bad + b"\n", label="t")


async def test_validate_view_runs_at_most_two_restic_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Index views are listed one at a time beside the snapshot listing.

    A transfer carrying many index files must not fan out one restic process
    per index: the bound is two concurrent processes (one index worker, one
    snapshot worker), whatever the file count. Each index still gets its own
    coverage, and cancellation leaves no stub in flight.
    """
    import inspect_ai.util._checkpoint._sandbox_restic.egress as egress

    dest = tmp_path / "sample" / "restic" / "sandboxes" / "default"
    dest.mkdir(parents=True)
    staging = tmp_path / "staging"
    index_ids = [f"{i:02d}" * 32 for i in range(1, 6)]
    snapshot_id = "ab" * 32
    written = (
        ["config", "keys/" + "cc" * 32]
        + [f"index/{i}" for i in index_ids]
        + [f"snapshots/{snapshot_id}"]
    )
    for rel in written:
        (staging / rel).parent.mkdir(parents=True, exist_ok=True)
        (staging / rel).write_bytes(b"x" * 40)
    memo = _IndexMemo(_index_memo_path(str(dest)))

    in_flight = 0
    peak = 0
    calls: list[str] = []
    gate = anyio.Event()

    async def fake_run(
        host_restic: Path,
        args: Sequence[str],
        view: Path,
        password: str,
        *,
        label: str,
        what: str,
        max_stdout_bytes: int | None = None,
    ) -> bytes:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        calls.append(args[0])
        try:
            await gate.wait()
            if args[0] == "list":
                return f"data {view.name.rsplit('-', 1)[1].ljust(64, '0')}\n".encode()
            if args[0] == "cat":
                return b'{"version": 2}'
            return json.dumps([{"id": snapshot_id, "tags": ["ckpt-00001"]}]).encode()
        finally:
            in_flight -= 1

    monkeypatch.setattr(egress, "_run_view_restic", fake_run)

    async def validate(view: Path) -> egress._Validated:
        return await _validate_view(
            Path("/usr/bin/false"),
            view,
            "pw",
            dest_repo=str(dest),
            staging=staging,
            existing=[],
            written=written,
            memo=memo,
            before_snapshots=set(),
            snapshot_id=snapshot_id,
            tag="ckpt-00001",
            repository_version_verified=False,
            label="t",
        )

    async def settled(count: int) -> None:
        with anyio.fail_after(10):
            while in_flight != count or not gate.is_set() and len(calls) < count:
                await anyio.sleep(0.01)

    results: list[egress._Validated] = []
    async with anyio.create_task_group() as tg:

        async def run() -> None:
            results.append(await validate(tmp_path / "view"))

        tg.start_soon(run)
        await settled(2)
        assert in_flight == 2 and sorted(calls) == ["cat", "list"]
        gate.set()
    assert peak == 2 and in_flight == 0
    # One list per index, one cat config, one snapshots listing: no more.
    assert sorted(calls) == ["cat"] + ["list"] * 5 + ["snapshots"]
    (validated,) = results
    assert validated.repository_version_checked
    assert set(validated.coverage) == set(index_ids)
    for index_id, blobs in validated.coverage.items():
        assert blobs == {"data:" + index_id[:16].ljust(64, "0")}
    assert validated.verified_id == snapshot_id

    # Cancellation mid-flight: the stubs exit and nothing keeps running.
    gate = anyio.Event()
    calls.clear()
    peak = 0
    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as tg:
            tg.start_soon(validate, tmp_path / "view-again")
            await settled(2)
            scope.cancel()
    assert in_flight == 0 and peak == 2


def test_index_memo_path_is_outside_the_sandbox_namespace(tmp_path: Path) -> None:
    """No sandbox name can collide with, or lengthen past a limit, a memo path."""
    sandboxes = tmp_path / "sample" / "restic" / "sandboxes"
    names = ["default", ".indexes-default.json", "index-memos", "x" * 255]
    paths = {name: _index_memo_path(str(sandboxes / name)) for name in names}
    assert len(set(paths.values())) == len(names)
    for name, path in paths.items():
        assert path.parent == sandboxes.parent / "index-memos"
        assert len(path.name) == 64 + len(".sqlite")
        for other in names:
            repo = sandboxes / other
            assert path != repo and repo not in path.parents
    with pytest.raises(ValueError, match="sandboxes"):
        _index_memo_path(str(tmp_path / "elsewhere" / "default"))


def test_index_memo_roundtrip_and_tolerance(tmp_path: Path) -> None:
    """The memo answers only for the ids asked, and anything unreadable is rebuilt."""
    path = tmp_path / "index-memos" / "m.sqlite"
    memo = _IndexMemo(path)
    assert memo.index_ids() == set()
    assert memo.repository_version() is None
    memo.record_repository_version(2)
    assert memo.repository_version() == 2
    memo.add({"i1": ["data:b1", "tree:t1"]})
    memo.add({"i2": {"data:b2"}})
    assert memo.index_ids() == {"i1", "i2"}
    assert memo.located_blobs(["data:b1", "data:b2", "data:b9"]) == {
        "data:b1",
        "data:b2",
    }
    assert memo.located_blobs([]) == set()
    memo.drop({"i1"})
    assert memo.index_ids() == {"i2"}
    assert memo.located_blobs(["data:b1", "tree:t1", "data:b2"]) == {"data:b2"}
    # Re-adding is idempotent, and lookups far past one IN batch work.
    memo.add({"i2": ["data:b2"]})
    assert memo.located_blobs([f"data:{i}" for i in range(1500)] + ["data:b2"]) == {
        "data:b2"
    }

    # Not a database: discarded and rebuilt empty, the version record with it.
    path.write_bytes(b"this is not sqlite" * 100)
    assert memo.index_ids() == set()
    assert memo.repository_version() is None
    memo.add({"i3": []})
    assert memo.index_ids() == {"i3"}
    # Another schema version: discarded.
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 99")
    assert memo.index_ids() == set()
    # A foreign SQLite file with no version: discarded, not adopted.
    path.unlink()
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE indexes (id INTEGER)")
    assert memo.index_ids() == set()
    assert memo.located_blobs(["data:b"]) == set()


def test_index_memo_work_is_flat_in_history(tmp_path: Path) -> None:
    """A fixed increment's memo work does not grow with the accepted history.

    Would fail against a memo that is read, materialised or rewritten whole:
    the large history below is about 14 MB of ids.
    """

    def increment_peak(history_indexes: int) -> int:
        memo = _IndexMemo(tmp_path / f"h{history_indexes}.sqlite")
        for n in range(history_indexes):
            memo.add({f"i{n:06d}": [f"data:{n:06d}{b:058d}" for b in range(1000)]})
        new = [f"data:new{b:057d}" for b in range(1000)]
        tracemalloc.start()
        try:
            memo.index_ids()
            assert memo.located_blobs(new) == set()
            memo.add({"i_new": new})
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    small, large = increment_peak(2), increment_peak(200)
    assert large < small + 512 * 1024, (small, large)
