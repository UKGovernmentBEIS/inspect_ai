"""Refusing writers that would change a merged log while its shards exist.

`recompute_metrics()`, `score()`/`score_async()` and `edit_score()` recreate
epoch reducers from their recorded names, which omit their arguments, so
they can replace the reductions the shards recorded. The merge trusts the
merged log's reductions once the shards are gone, so these writers refuse a
merged log until the merge has deleted its shards (decision: Ransom,
2026-10-26).
"""

from inspect_ai._util.asyncfiles import (
    AsyncFilesystem,
    is_s3_filename,
    s3_bucket_and_key,
)
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
        OSError: The directory could not be inspected for a reason other
            than its absence (on S3, botocore's `ClientError`).
    """
    shards_dir = _shards_dir(log)
    if shards_dir is None:
        return
    if _holds_entries(shards_dir):
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


def _holds_entries(shards_dir: str) -> bool:
    """Whether `shards_dir` holds an entry, as :func:`_has_entries` counts them.

    Only a missing directory counts as empty: fsspec's `exists()` returns
    False on any error, a denied inspection included. S3 is listed with the
    boto3 client, since s3fs is not supported under a configured Trio
    backend.
    """
    if is_s3_filename(shards_dir):
        bucket, prefix = s3_bucket_and_key(shards_dir)
        prefix = prefix.rstrip("/") + "/"
        # keys come in order, so the directory's own folder marker (not an
        # entry) is first and a second key is an entry
        response = (
            AsyncFilesystem()
            .s3_client()
            .list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=2)
        )
        return any(obj["Key"] != prefix for obj in response.get("Contents", []))
    try:
        return bool(filesystem(shards_dir).ls(shards_dir))
    except FileNotFoundError:
        return False


async def _has_entries(fs: AsyncFilesystem, shards_dir: str) -> bool:
    try:
        listing = await fs.list_dir(shards_dir)
    except FileNotFoundError:
        return False
    return bool(listing.files or listing.dirs)


def _live_shards(log: EvalLog, shards_dir: str, action: str) -> ShardSetError:
    if log.status == "success":
        finish = "finish merging (merge with delete_shards)"
    else:
        # delete_shards needs a complete set
        finish = (
            f"the merge is incomplete ({log.status}): re-run the incomplete "
            "shards and merge with delete_shards, or delete the shards "
            "directory by hand to abandon them,"
        )
    return ShardSetError(
        f"{log.location} is a merge of shards that still exist in {shards_dir}; "
        f"{finish} before {action} it."
    )
