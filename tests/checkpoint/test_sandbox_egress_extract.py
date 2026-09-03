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

import hashlib
import io
import tarfile
from collections.abc import Collection, Sequence
from pathlib import Path

import pytest

from inspect_ai.util._checkpoint._sandbox_restic.egress import (
    EgressVerificationError,
    _extract_verified,
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
SNAP = b"snapshot bytes"
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
    tar = _tar(tmp_path, _file(SNAP_NAME, b"different bytes"))

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


def test_rejects_extraction_exceeding_byte_cap(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    tar = _tar(tmp_path, _file(SNAP_NAME, SNAP), _file(PACK_NAME, PACK))

    with pytest.raises(EgressVerificationError, match="max_sandbox_snapshot_bytes"):
        _extract(tar, dest, [SNAP_NAME, PACK_NAME], max_bytes=len(SNAP) + 10)
    assert _files(dest) == set()
    assert not list(dest.rglob("*.partial"))
