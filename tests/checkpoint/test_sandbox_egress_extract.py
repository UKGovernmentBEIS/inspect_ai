"""Regression tests for host-side extraction of sandbox egress tarballs.

``_extract_tar`` unpacks a tarball whose bytes were produced *inside* the
sandbox, onto the host filesystem. The archive is therefore untrusted: a
sandboxed agent could plant members with ``..`` traversal, absolute paths,
or outside-pointing symlinks to write files outside ``dest_repo`` on the
host (CVE-2007-4559 class). Extraction must use the ``data`` filter so such
members are rejected.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from inspect_ai.util._checkpoint._sandbox_restic.egress import _extract_tar


def _tar_with(*members: tarfile.TarInfo, data: bytes = b"pwned") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for member in members:
            if member.issym() or member.islnk():
                tar.addfile(member)
            else:
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
    return buf.getvalue()


def test_extracts_benign_tarball(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    member = tarfile.TarInfo(name="data/ab/cdef")

    _extract_tar(_tar_with(member, data=b"pack"), str(dest))

    assert (dest / "data" / "ab" / "cdef").read_text() == "pack"


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    member = tarfile.TarInfo(name="../escape.txt")

    with pytest.raises(tarfile.FilterError):
        _extract_tar(_tar_with(member), str(dest))

    assert not (tmp_path / "escape.txt").exists()


def test_neutralizes_absolute_path(tmp_path: Path) -> None:
    # The "data" filter strips the leading slash from an absolute member
    # name, so the entry lands inside dest rather than at its absolute
    # location on the host. The security property is that nothing is
    # written outside dest.
    dest = tmp_path / "dest"
    dest.mkdir()
    target = tmp_path / "abs_escape.txt"
    member = tarfile.TarInfo(name=str(target))

    _extract_tar(_tar_with(member), str(dest))

    assert not target.exists()


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    link = tarfile.TarInfo(name="link")
    link.type = tarfile.SYMTYPE
    link.linkname = "../outside"

    with pytest.raises(tarfile.FilterError):
        _extract_tar(_tar_with(link), str(dest))

    assert not (tmp_path / "outside").exists()
