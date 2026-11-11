"""Tests for the archive rewriting helpers in ``inspect_ai._util.zipfile``."""

import io
import os
import tempfile
import warnings
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

import anyio
import pytest

from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.zipfile import (
    RawMemberWriter,
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


def _raw_bytes(path: str, info: zipfile.ZipInfo) -> bytes:
    """A member's compressed bytes, located from its local header."""
    with open(path, "rb") as file:
        file.seek(info.header_offset)
        header = file.read(30)
        name_length = int.from_bytes(header[26:28], "little")
        extra_length = int.from_bytes(header[28:30], "little")
        file.seek(info.header_offset + 30 + name_length + extra_length)
        return file.read(info.compress_size)


@pytest.mark.parametrize("zip64", [False, True])
async def test_raw_member_writer_copies_members_that_read_back_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, zip64: bool
) -> None:
    if zip64:
        # sizes and offsets past the limit use ZIP64 fields, as for 4 GiB
        monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 1000)
    members = {
        "stored.json": (zipfile.ZIP_STORED, os.urandom(4096)),
        "deflated.json": (zipfile.ZIP_DEFLATED, b"deflated " * 1000),
        "zstd.json": (zipfile_compress_kwargs["compression"], b"zstd " * 1000),
        "empty.json": (zipfile.ZIP_DEFLATED, b""),
    }
    source = str(tmp_path / "source.zip")
    with zipfile.ZipFile(source, "w") as zf:
        for name, (method, data) in members.items():
            zf.writestr(name, data, compress_type=method)

    target = str(tmp_path / "target.zip")
    async with AsyncFilesystem() as fs:
        reader = AsyncZipReader(fs, source)
        with zipfile.ZipFile(target, "w", **zipfile_compress_kwargs) as zf:
            zf.writestr("first.json", os.urandom(2048))
            for entry in (await reader.entries()).entries:
                writer = RawMemberWriter(zf, entry.filename, entry.compression_method)
                async for chunk in await reader.open_member_raw(entry):
                    writer.write(chunk)
                assert entry.crc32 is not None
                writer.finish(entry.crc32, entry.uncompressed_size)
            zf.writestr("last.json", b"last")

        with zipfile.ZipFile(source) as src, zipfile.ZipFile(target) as dst:
            for name, (method, data) in members.items():
                info = dst.getinfo(name)
                assert info.compress_type == method
                assert dst.read(name) == data
                assert _raw_bytes(target, info) == _raw_bytes(source, src.getinfo(name))
            assert dst.read("last.json") == b"last"
            if zip64:
                assert dst.getinfo("stored.json").file_size > zipfile.ZIP64_LIMIT
                assert dst.getinfo("last.json").header_offset > zipfile.ZIP64_LIMIT
        copied = AsyncZipReader(fs, target, verify_crc=True)
        for name, (_, data) in members.items():
            assert await copied.read_member_fully(name) == data
            async with await copied.open_member(name) as stream:
                assert b"".join([chunk async for chunk in stream]) == data


def test_raw_member_writer_refuses_an_unseekable_archive() -> None:
    class Unseekable(io.RawIOBase):
        def writable(self) -> bool:
            return True

        def write(self, data: Any) -> int:
            return len(data)

    with zipfile.ZipFile(Unseekable(), "w") as zf:
        with pytest.raises(ValueError, match="seekable"):
            RawMemberWriter(zf, "member.json", zipfile.ZIP_DEFLATED)
