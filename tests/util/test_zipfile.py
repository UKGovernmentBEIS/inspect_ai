"""Tests for the archive rewriting helpers in ``inspect_ai._util.zipfile``."""

import os
import tempfile
import warnings
import zipfile
from typing import BinaryIO

import anyio

from inspect_ai._util.zipfile import (
    compact_zip,
    copy_live_members,
    zip_dead_bytes,
    zip_needs_rewrite,
    zipfile_compress_kwargs,
)


def _archive(members: list[tuple[str, bytes]]) -> BinaryIO:
    """A closed temp zip holding ``members`` in order (a repeated name supersedes)."""
    file: BinaryIO = tempfile.TemporaryFile()
    with (
        warnings.catch_warnings(),
        zipfile.ZipFile(file, "w", **zipfile_compress_kwargs) as archive,
    ):
        warnings.filterwarnings("ignore", message="Duplicate name:")
        for name, data in members:
            archive.writestr(name, data)
    file.seek(0)
    return file


def _members(file: BinaryIO) -> dict[str, bytes]:
    file.seek(0)
    with zipfile.ZipFile(file, "r") as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_copy_live_members_takes_the_last_entry_per_name_and_excludes() -> None:
    src_file = _archive([("a", b"old a"), ("b", b"b"), ("a", b"new a")])
    out: BinaryIO = tempfile.TemporaryFile()
    with (
        zipfile.ZipFile(src_file, "r") as src,
        zipfile.ZipFile(out, "w", **zipfile_compress_kwargs) as dst,
    ):
        copy_live_members(src, dst, exclude=frozenset({"b"}))
        # the source ZipInfo is preserved, not re-derived
        assert dst.getinfo("a").compress_type == src.getinfo("a").compress_type
    assert _members(out) == {"a": b"new a"}
    out.close()
    src_file.close()


async def test_compact_zip_keeps_only_the_live_set_and_sheds_dead_bytes() -> None:
    # an incompressible superseded "a": its bytes stay in the file as dead
    # bytes, well beyond the measure's 20-byte-per-member header slack
    src_file = _archive(
        [("a", os.urandom(4096)), ("b", b"b"), ("a", b"new a"), ("c", b"c")]
    )
    with zipfile.ZipFile(src_file, "r") as archive:
        assert zip_dead_bytes(archive) > 4000

    compacted = await anyio.to_thread.run_sync(
        compact_zip, src_file, frozenset({"a", "b"})
    )
    assert _members(compacted) == {"a": b"new a", "b": b"b"}
    compacted.seek(0)
    with zipfile.ZipFile(compacted, "r") as archive:
        assert zip_dead_bytes(archive) == 0
    compacted.close()
    src_file.close()


def test_zip_needs_rewrite_for_excluded_members_and_directory_pruned_gaps() -> None:
    complete = _archive([("a", b"a"), ("b", b"b")])
    assert zip_needs_rewrite(complete, lambda name: True) is False
    # a member the live predicate rejects
    assert zip_needs_rewrite(complete, lambda name: name != "b") is True
    complete.close()

    # a member pruned from the directory leaves its bytes as a gap: every
    # listed member is live, yet the file must still be rewritten to shed it
    pruned = _archive([("a", b"a"), ("gone", b"secret payload"), ("b", b"b")])
    with zipfile.ZipFile(pruned, "a", **zipfile_compress_kwargs) as archive:
        archive.filelist = [i for i in archive.filelist if i.filename != "gone"]
        archive.NameToInfo.pop("gone")
        archive.writestr("c", b"c")  # a write, so close rewrites the directory
    pruned.seek(0)
    with zipfile.ZipFile(pruned, "r") as archive:
        assert set(archive.namelist()) == {"a", "b", "c"}
    assert zip_needs_rewrite(pruned, lambda name: True) is True
    pruned.close()


def test_zip_dead_bytes_is_zero_for_a_fresh_archive() -> None:
    fresh = _archive([("a", b"a" * 1000), ("b", b"b")])
    with zipfile.ZipFile(fresh, "r") as archive:
        assert zip_dead_bytes(archive) == 0
    fresh.close()
