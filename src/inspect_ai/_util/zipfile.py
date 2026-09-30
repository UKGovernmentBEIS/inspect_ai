"""ZIP file helpers and monkey-patches for zstd support.

On Python < 3.14 we import ``zipfile_zstd`` to monkey-patch zstandard
compression into the stdlib ``zipfile`` module. Python 3.14+ handles zstd
natively via stdlib.

Additionally, we install a second monkey-patch on ``zipfile._get_compressor``
that caps each emitted zstd frame at ``_MAX_INPUT_PER_FRAME`` bytes of input.
Large single zstd frames (>= 256 MiB compressed) trigger an overflow bug in
the pure-JS ``fzstd`` decoder used by our viewers; multi-framing keeps every
frame well under that threshold.
"""

from __future__ import annotations

import logging
import sys
import tempfile
import zipfile
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, BinaryIO

import anyio
import anyio.from_thread

if TYPE_CHECKING:
    import zstandard

logger = logging.getLogger(__name__)

# On Python < 3.14, monkey-patch zipfile to support zstandard compression.
if sys.version_info < (3, 14):
    import zipfile_zstd  # type: ignore[import-not-found, import-untyped]  # noqa: F401

# Resolve once so the rest of the module can use a plain int; also fails loudly
# at import time rather than at first call if the attribute is ever missing.
_ZIP_ZSTANDARD: int = zipfile.ZIP_ZSTANDARD  # type: ignore[attr-defined]

zipfile_compress_kwargs: dict[str, Any] = {
    "compression": _ZIP_ZSTANDARD,
    "compresslevel": None,
}


# 200 MiB. Well under fzstd's 256 MiB (2^28) compressed-frame overflow
# threshold, applied to *input* bytes which compress smaller.
_MAX_INPUT_PER_FRAME = 200 * 1024 * 1024

# Matches zipfile_zstd's hardcoded default so multi-frame and single-frame zip
# writes use the same thread count. If zipfile_zstd ever changes its default,
# update here too.
_ZSTD_THREADS = 12


class _MultiFrameZstdCompressObj:
    """A zstd compressobj that chunks its output into multiple frames.

    Wraps a ``zstandard`` compressobj and flushes it (finalizing the current
    frame) and replaces it (starting a new frame) every
    ``_MAX_INPUT_PER_FRAME`` bytes of input. Multi-frame zstd streams are
    valid per spec -- any compliant decoder reads them transparently.
    """

    def __init__(self, factory: Callable[[], zstandard.ZstdCompressionObj]) -> None:
        self._factory = factory
        self._obj = factory()
        self._input_bytes = 0

    def compress(self, data: bytes) -> bytes:
        view = memoryview(data)
        pieces: list[bytes] = []
        offset = 0
        n = len(view)
        while offset < n:
            remaining_cap = _MAX_INPUT_PER_FRAME - self._input_bytes
            end = min(offset + remaining_cap, n)
            chunk = view[offset:end]
            pieces.append(self._obj.compress(chunk))
            self._input_bytes += end - offset
            offset = end
            if self._input_bytes >= _MAX_INPUT_PER_FRAME:
                pieces.append(self._obj.flush())
                self._obj = self._factory()
                self._input_bytes = 0
        return b"".join(pieces)

    def flush(self) -> bytes:
        # If the last ``compress()`` call landed exactly on the frame boundary,
        # ``self._obj`` was replaced with a fresh compressobj that has received
        # no bytes. Flushing it would append an empty 9-byte trailing frame.
        if self._input_bytes == 0:
            return b""
        return self._obj.flush()


class _MultiFrameZstdDecompressObj:
    """A zstd decompressobj that transparently spans multiple frames.

    ``zstandard.ZstdDecompressor().decompressobj()`` stops at the first frame
    boundary and marks ``eof=True``.  When the compressor splits large entries
    into multiple frames (see ``_MultiFrameZstdCompressObj``), the reader must
    recognise the frame boundary, start a fresh inner decompressobj, and
    continue until all compressed bytes have been consumed.

    The stdlib ``zipfile._read1`` path for non-deflate compression does:

        data = self._decompressor.decompress(data)
        self._eof = self._decompressor.eof or self._compress_left <= 0

    We return ``eof=False`` always so that ``self._eof`` is driven purely by
    ``self._compress_left <= 0`` (all compressed bytes fed).  Meanwhile,
    ``decompress`` buffers leftover bytes from a completed frame and feeds them
    into the next inner decompressobj.

    Since CPython gh-156002, ``_read1`` calls ``decompress(data, max_length)``
    and reads more compressed bytes only while ``needs_input`` is True (draining
    with ``decompress(b"")`` otherwise); both are provided here.
    """

    def __init__(self) -> None:
        import zstandard as zstd  # local import -- already a hard dep

        self._dctx: zstandard.ZstdDecompressor = zstd.ZstdDecompressor()
        self._obj: zstandard.ZstdDecompressionObj = self._dctx.decompressobj()
        self._pending: bytes = b""

    def decompress(self, data: bytes, max_length: int = -1) -> bytes:
        # max_length is accepted but not enforced: the zstandard decompressobj has
        # no output bound, so withholding bytes here would only copy an expansion
        # that is already allocated. ZipExtFile buffers oversize returns anyway.
        self._pending += data
        out = b""
        while self._pending:
            result = self._obj.decompress(self._pending)
            out += result
            if self._obj.eof:
                # Inner frame complete; unused_data holds the start of the next.
                self._pending = self._obj.unused_data
                self._obj = self._dctx.decompressobj()
            else:
                # All pending input consumed; wait for more.
                self._pending = b""
                break
        return out

    def flush(self) -> bytes:
        return b""

    @property
    def eof(self) -> bool:
        # Always False: let compress_left drive the outer EOF check.
        return False

    @property
    def needs_input(self) -> bool:
        # decompress() never leaves input or output pending; nothing to drain.
        return True


def _install_multiframe_patches() -> None:
    """Install multi-frame zstd compressor and decompressor patches.

    Idempotent. Wraps whatever ``_get_compressor`` / ``_get_decompressor`` were
    installed before us (stdlib on Py >= 3.14; ``zipfile_zstd``'s versions on
    Py < 3.14), so compression level and thread count are preserved.
    """
    if getattr(zipfile, "_inspect_ai_multiframe_installed", False):
        return

    original_compressor = zipfile._get_compressor  # type: ignore[attr-defined]
    original_decompressor = zipfile._get_decompressor  # type: ignore[attr-defined]

    def patched_compressor(compress_type: int, compresslevel: int | None = None) -> Any:
        if compress_type == _ZIP_ZSTANDARD:
            # Share one ``ZstdCompressor`` across all frames of the entry.
            # Delegating to ``original_compressor`` would instead create a
            # fresh ``ZstdCompressor(threads=N)`` per frame, re-initialising
            # its thread pool every 200 MiB.
            import zstandard

            level = 3 if compresslevel is None else compresslevel
            compressor = zstandard.ZstdCompressor(level=level, threads=_ZSTD_THREADS)
            return _MultiFrameZstdCompressObj(compressor.compressobj)
        return original_compressor(compress_type, compresslevel)

    def patched_decompressor(compress_type: int) -> Any:
        if compress_type == _ZIP_ZSTANDARD:
            return _MultiFrameZstdDecompressObj()
        return original_decompressor(compress_type)

    zipfile._get_compressor = patched_compressor  # type: ignore[attr-defined]
    zipfile._get_decompressor = patched_decompressor  # type: ignore[attr-defined]
    zipfile._inspect_ai_multiframe_installed = True  # type: ignore[attr-defined]


_install_multiframe_patches()


__all__ = ["zipfile_compress_kwargs"]


# ---------------------------------------------------------------------------
# Archive rewriting helpers
#
# An append-mode ZipFile never removes bytes: a member "pruned" from the
# central directory, or superseded by a later write under the same name, stays
# in the member area as dead bytes. These helpers measure that and rewrite an
# archive down to its live members. They know nothing about eval logs; the
# recorders decide which members are live and when a rewrite is worth it.


def copy_live_members(
    src: zipfile.ZipFile,
    dst: zipfile.ZipFile,
    exclude: frozenset[str] = frozenset(),
    *,
    cancellable: bool = False,
) -> None:
    """Copy each name's last member from ``src`` to ``dst``, streaming.

    Dedupes by member name, last entry winning — a duplicate name is how a
    writer supersedes a member (read-by-name resolves to the last entry), and
    copying every info would write those superseded bytes twice. Opening the
    destination entry with the source ``ZipInfo`` preserves the original
    compression type / date_time / external_attr; the data still round-trips
    through decompress + recompress, streamed in chunks so a large member
    never sits in memory whole. Blocking — run in a worker thread when called
    from the event loop. ``cancellable`` requires an AnyIO worker and checks
    its host task's cancellation between chunks.
    """
    infos = {info.filename: info for info in src.infolist()}
    for info in infos.values():
        if info.filename in exclude:
            continue
        with (
            src.open(info, "r") as reader,
            dst.open(info, "w", force_zip64=True) as writer,
        ):
            while True:
                if cancellable:
                    anyio.from_thread.check_cancelled()
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)


def compact_zip(src_file: BinaryIO, live: frozenset[str]) -> BinaryIO:
    """Copy the live members of a closed zip temp file into a fresh temp file.

    Live means the last member under each name in ``live``; pruned and
    superseded members are left behind. Take ``live`` from the writer's
    in-memory central directory rather than the file's: ``ZipFile.close``
    rewrites the on-disk directory only after a write, so a directory-only
    prune since the last write is not on disk yet and the closed file's
    directory may still list pruned members. Blocking (decompress +
    recompress of every member) — run in a worker thread created by AnyIO.
    Cancellation is checked between chunks and closes the incomplete output
    before propagating to the caller.
    """
    src_file.seek(0)
    out: BinaryIO = tempfile.TemporaryFile()
    try:
        with (
            zipfile.ZipFile(src_file, "r") as src,
            zipfile.ZipFile(out, "w", **zipfile_compress_kwargs) as dst,
        ):
            copy_live_members(
                src, dst, exclude=frozenset(src.namelist()) - live, cancellable=True
            )
    except BaseException:
        out.close()
        raise
    return out


def zip_needs_rewrite(file: BinaryIO, is_live: Callable[[str], bool]) -> bool:
    """Whether an archive holds members ``is_live`` rejects, or bytes no member accounts for.

    Answers "can this file be adopted as-is, or must it be rewritten to shed
    what it should not carry" without inflating any member: a member outside
    the live set, or a gap between members (a pruned member's leftover
    bytes, which ordinary readers no longer list but still recoverable from
    the file), both require a rewrite. Walks exact local header lengths —
    estimating from central-directory extras can miss small gaps, especially
    with ZIP64 — and conservatively requires a rewrite for data descriptors
    or any layout it cannot verify. Blocking local I/O — run in a worker
    thread.
    """
    file.seek(0)
    with zipfile.ZipFile(file, "r") as archive:
        if any(not is_live(name) for name in archive.NameToInfo):
            return True
        end = 0
        for info in sorted(archive.NameToInfo.values(), key=lambda i: i.header_offset):
            if info.header_offset != end or info.flag_bits & 0x08:
                return True
            file.seek(info.header_offset)
            header = file.read(30)
            if len(header) != 30 or header[:4] != b"PK\x03\x04":
                return True
            name_length = int.from_bytes(header[26:28], "little")
            extra_length = int.from_bytes(header[28:30], "little")
            end += 30 + name_length + extra_length + info.compress_size
        return end != archive.start_dir


def zip_dead_bytes(archive: zipfile.ZipFile) -> int:
    """Bytes of the member area no live member accounts for (0 for a fresh archive).

    The member area runs from offset 0 to ``start_dir`` (where the central
    directory is written at close); whatever the live members' local headers
    and compressed data don't cover is dead — pruned or superseded members,
    including any inherited when the archive was copied from another. A local
    header is reconstructed as ``FileHeader(zip64=True)``: exact for members
    written with ``force_zip64``, and 20 bytes over for ``writestr`` members,
    so the count is if anything an under-estimate.
    """
    live = sum(
        len(info.FileHeader(zip64=True)) + info.compress_size
        for info in archive.NameToInfo.values()
    )
    return max(0, archive.start_dir - live)
