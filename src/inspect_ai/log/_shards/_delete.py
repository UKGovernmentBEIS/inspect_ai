"""Deleting a merged log's shards directory.

The caller must be the only process operating on the log and its shards
directory: no worker still writing, no other merge or deletion. Nothing is
guaranteed otherwise. An interrupted deletion leaves objects behind; running
it again, or deleting the directory by hand, finishes it.
"""

import re
import shutil
from contextlib import suppress

import anyio

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.file import filesystem, local_path
from inspect_ai._util.log_layout import eval_shards_dir

from ._publish import is_local

# fsspec expands these in paths it deletes, also inside a recursive delete
_GLOB_CHARS = re.compile(r"[*?[]")


async def remove_shards_dir(
    log: str, *, include_log: bool = False, fs: AsyncFilesystem | None = None
) -> None:
    """Delete the shards directory of the merged log `log`.

    Everything under ``<name>.shards/`` is deleted: shard attempts, sample
    buffers, checkpoint directories, S3 folder markers and any other object.
    A remote directory is deleted with one recursive delete on the
    filesystem built from `log` itself, so connection details in the URL
    (an Azure account, a WebHDFS host) are kept. A missing directory is not
    an error.

    Args:
        log: The merged log ``<dir>/<name>.eval``.
        include_log: Delete the merged log too, before the shards.
        fs: Filesystem to use (a new one when omitted).

    Raises:
        ValueError: A remote `log` holds glob characters (see
            :func:`check_deletable`); nothing is deleted.
    """
    check_deletable(log)
    if fs is None:
        async with AsyncFilesystem() as owned:
            await remove_shards_dir(log, include_log=include_log, fs=owned)
        return

    if is_local(log):
        log = local_path(log)
    shards_dir = eval_shards_dir(log)
    if include_log:
        with suppress(FileNotFoundError):
            await fs.delete_file(log)
    if is_local(shards_dir):
        await anyio.to_thread.run_sync(_remove_local_dir, shards_dir)
        return
    # on the loop thread: to_thread over remote fsspec work can deadlock
    with suppress(FileNotFoundError):
        filesystem(shards_dir).rm(shards_dir, recursive=True)


def check_deletable(log: str) -> None:
    """Refuse to delete the shards of a remote `log` whose URL holds glob characters.

    fsspec expands `*`, `?` and `[` in the paths it deletes, so deleting
    `run?.shards` would also delete `run1.shards`. Local paths are deleted by
    their exact path and are not refused.

    Raises:
        ValueError: `log` is remote and holds `*`, `?` or `[`.
    """
    if not is_local(log) and _GLOB_CHARS.search(log):
        raise ValueError(
            f"Cannot delete the shards of {log}: its location holds a glob "
            "character (*, ? or [), which the storage backend would expand to "
            "other paths. Delete the shards directory by hand."
        )


def _remove_local_dir(path: str) -> None:
    with suppress(FileNotFoundError):
        shutil.rmtree(path)
