"""Refusing writers that would change a merged log while its shards exist.

`recompute_metrics()`, `score()`/`score_async()` and `edit_score()` recreate
epoch reducers from their recorded names, which omit their arguments, so
they can replace the reductions the shards recorded. The merge trusts the
merged log's reductions once the shards are gone, so these writers refuse a
merged log until the merge has deleted its shards (decision: Ransom,
2026-10-26).
"""

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.file import filesystem, local_path
from inspect_ai._util.log_layout import eval_shards_dir
from inspect_ai.log._log import EvalLog

from ._errors import ShardSetError


def check_shards_merged(log: EvalLog, action: str) -> None:
    """Refuse `action` on a merged log whose shards directory still exists.

    A log with no `eval.shards` (an ordinary log) or no `location` (built in
    memory) is not checked.

    Raises:
        ShardSetError: The log is a merged log and its `<name>.shards/`
            directory exists and is not empty.
    """
    shards_dir = _shards_dir(log)
    if shards_dir is None:
        return
    fs = filesystem(shards_dir)
    if fs.exists(shards_dir) and fs.ls(shards_dir):
        raise _live_shards(log, shards_dir, action)


async def check_shards_merged_async(log: EvalLog, action: str) -> None:
    """Refuse `action` on a merged log whose shards directory still exists.

    See :func:`check_shards_merged`.
    """
    shards_dir = _shards_dir(log)
    if shards_dir is None:
        return
    async with AsyncFilesystem() as fs:
        if await _has_entries(fs, shards_dir):
            raise _live_shards(log, shards_dir, action)


def _shards_dir(log: EvalLog) -> str | None:
    if log.eval.shards is None or not log.location:
        return None
    return eval_shards_dir(local_path(log.location))


async def _has_entries(fs: AsyncFilesystem, shards_dir: str) -> bool:
    try:
        listing = await fs.list_dir(shards_dir)
    except FileNotFoundError:
        return False
    return bool(listing.files or listing.dirs)


def _live_shards(log: EvalLog, shards_dir: str, action: str) -> ShardSetError:
    return ShardSetError(
        f"{log.location} is a merge of shards that still exist in {shards_dir}; "
        f"finish merging (merge with delete_shards) before {action} it."
    )
