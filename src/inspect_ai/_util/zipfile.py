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

import functools
import logging
import sys
import zipfile
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# On Python < 3.14, monkey-patch zipfile to support zstandard compression.
if sys.version_info < (3, 14):
    import zipfile_zstd  # type: ignore[import-not-found, import-untyped]  # noqa: F401

zipfile_compress_kwargs: dict[str, Any] = {
    "compression": zipfile.ZIP_ZSTANDARD,  # type: ignore[attr-defined]
    "compresslevel": None,
}


# 200 MiB. Well under fzstd's 256 MiB (2^28) compressed-frame overflow
# threshold, applied to *input* bytes which compress smaller.
_MAX_INPUT_PER_FRAME = 200 * 1024 * 1024


class _MultiFrameZstdCompressObj:
    """A zstd compressobj that chunks its output into multiple frames.

    Wraps a ``zstandard`` compressobj and flushes it (finalizing the current
    frame) and replaces it (starting a new frame) every
    ``_MAX_INPUT_PER_FRAME`` bytes of input. Multi-frame zstd streams are
    valid per spec -- any compliant decoder reads them transparently.
    """

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._obj = factory()
        self._input_bytes = 0

    def compress(self, data: bytes) -> bytes:
        out = b""
        offset = 0
        while offset < len(data):
            remaining_cap = _MAX_INPUT_PER_FRAME - self._input_bytes
            chunk = data[offset : offset + remaining_cap]
            out += self._obj.compress(chunk)
            self._input_bytes += len(chunk)
            offset += len(chunk)
            if self._input_bytes >= _MAX_INPUT_PER_FRAME:
                out += self._obj.flush()
                self._obj = self._factory()
                self._input_bytes = 0
        return out

    def flush(self) -> bytes:
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
    """

    def __init__(self) -> None:
        import zstandard  # local import — already a hard dep via zipfile_zstd

        self._dctx = zstandard.ZstdDecompressor()
        self._obj = self._dctx.decompressobj()
        self._pending: bytes = b""

    def decompress(self, data: bytes) -> bytes:
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
        if compress_type == zipfile.ZIP_ZSTANDARD:  # type: ignore[attr-defined]
            factory = functools.partial(
                original_compressor, compress_type, compresslevel
            )
            return _MultiFrameZstdCompressObj(factory)
        return original_compressor(compress_type, compresslevel)

    def patched_decompressor(compress_type: int) -> Any:
        if compress_type == zipfile.ZIP_ZSTANDARD:  # type: ignore[attr-defined]
            return _MultiFrameZstdDecompressObj()
        return original_decompressor(compress_type)

    zipfile._get_compressor = patched_compressor  # type: ignore[attr-defined]
    zipfile._get_decompressor = patched_decompressor  # type: ignore[attr-defined]
    zipfile._inspect_ai_multiframe_installed = True  # type: ignore[attr-defined]


_install_multiframe_patches()


__all__ = ["zipfile_compress_kwargs"]
