"""Async filesystem helpers local to the checkpointing subsystem.

Bridges to the project-wide :class:`AsyncFilesystem` for ops that
class doesn't yet expose. Kept here (rather than promoted to
``inspect_ai._util.asyncfiles``) until the S3 enablement step settles
the broader API.
"""

from __future__ import annotations

import anyio.to_thread

from inspect_ai._util.asyncfiles import is_s3_filename
from inspect_ai._util.file import filesystem


async def async_mkdir(path: str, *, exist_ok: bool = True) -> None:
    """Async mkdir across local and remote filesystems.

    For S3 URLs this is a no-op — S3 has no directory concept; pack
    files are created directly under their full key. For everything
    else, delegates to the sync ``filesystem(path).mkdir(...)`` wrapper
    (which already handles fsspec's per-backend mkdir quirks) via
    ``anyio.to_thread.run_sync``.
    """
    if is_s3_filename(path):
        return
    await anyio.to_thread.run_sync(_mkdir_sync, path, exist_ok)


def _mkdir_sync(path: str, exist_ok: bool) -> None:
    filesystem(path).mkdir(path, exist_ok=exist_ok)
