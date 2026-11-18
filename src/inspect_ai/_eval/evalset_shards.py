"""Eval-set startup merge of the shard sets in its log directory.

Before an eval set pairs its tasks with their logs, each `<name>.shards/`
directory in the log directory is merged into `<name>.eval` (see
`merge_shard_sets`). The eval set then treats the merged log like any other
log: an incomplete or failed one is retried as an ordinary, unsharded run.
"""

import contextlib
import copy
import functools
import logging
from collections.abc import Iterator
from typing import NamedTuple

import anyio
from rich.markup import escape

from inspect_ai._util._async import run_coroutine, tg_collect
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.error import PrerequisiteError, WriteConflictError
from inspect_ai._util.log_layout import (
    eval_log_for_shards_dir,
    log_basename,
    merged_log_task_id,
)
from inspect_ai._util.path import native_path
from inspect_ai.log import (
    EvalLog,
    ShardSelectionError,
    ShardSetError,
    merge_eval_log_shards_async,
    read_eval_log_async,
)
from inspect_ai.log._file import EvalLogInfo, list_eval_logs
from inspect_ai.log._shards._walk import list_shard_set, listing_root, shard_companion

from .eval_set_manifest import selected_sample_ids
from .evalset import Log, task_identifier
from .task import Epochs
from .task.resolved import ResolvedTask, resolved_task_names
from .task.task import resolve_epochs, resolve_task_epochs, task_with

logger = logging.getLogger(__name__)

# shard sets identified or merged at once by the eval-set startup merge
_MAX_CONCURRENT_SHARD_SETS = 4


def shard_sets_in(log_dir: str, log_files: list[EvalLogInfo]) -> list[str]:
    """The `<name>.shards/` directories that hold a listed log file, sorted."""
    root = listing_root(log_dir)
    return sorted(
        {
            companion
            for info in log_files
            if (companion := shard_companion(root, info.name)) is not None
        }
    )


def refuse_scanner_with_shards(log_dir: str) -> None:
    """Refuse scanners over a log directory that holds shard sets.

    Raises:
        PrerequisiteError: The log directory holds a `<name>.shards/` directory.
    """
    shard_sets = shard_sets_in(log_dir, list_eval_logs(log_dir))
    if shard_sets:
        raise PrerequisiteError(
            "[bold]ERROR[/bold]: eval_set() cannot run scanners over sharded "
            f"tasks yet, and {_display(shard_sets[0])} holds shards. Run the eval "
            "set without scanners, or move the .shards directories and their "
            "merged logs out of the log directory."
        )


class _ShardSet(NamedTuple):
    """A `<name>.shards/` directory in an eval set's log directory, and its task."""

    shards_dir: str
    merged: str
    header: EvalLog
    """The merged log's header, or the first shard's current attempt's."""
    task_id: str
    """The merged log's task id, or the one the merge would give it."""
    identifier: str
    """The task identifier of `header`."""
    task: ResolvedTask


def merge_shard_sets(
    log_dir: str,
    log_files: list[EvalLogInfo],
    logs: list[Log],
    all_tasks: list[tuple[str, ResolvedTask]],
    *,
    epochs: int | Epochs | None,
    limit: int | tuple[int, int] | None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None,
) -> bool:
    """Merge every shard set in an eval set's log directory, before its logs are paired.

    Each `<name>.shards/` that holds a listed log file is matched to the task
    in `all_tasks` with the same identifier, read from its merged log
    `<name>.eval` or else from its first shard's current attempt, and merged
    with `allow_incomplete=True` and the eval set's selection of that task's
    samples as ids. A shard set that matches no task is left alone with a
    warning. The eval set then pairs, completes and retries the merged log
    like any other log.

    A shard set is not merged once an unsharded log has its task id (the
    merged log's, or the one the merge would give it): that log is a retry
    seeded from the merged log, and the eval set continues from it. A shard
    attempt newer than every such retry was added after it and is refused.

    Args:
        log_dir: The eval set's log directory.
        log_files: Its listing.
        logs: The listed logs outside shard sets, with their headers.
        all_tasks: The eval set's tasks and their identifiers.
        epochs: The eval set's epochs, applied to the task passed to the merge.
        limit: The eval set's `limit`.
        sample_id: The eval set's `sample_id`.

    Returns:
        Whether any merge wrote its merged log.

    Raises:
        PrerequisiteError: A shard set holds only stray files, shares its task
            id with a log or shard set of another task, holds a shard attempt
            newer than its unsharded retries, the eval set selects none of its
            task's samples, or its merge failed (the merge's exception is the
            cause). The other merges still running are cancelled.
    """
    shard_sets = shard_sets_in(log_dir, log_files)
    if not shard_sets:
        return False
    by_name = {log.info.name: log for log in logs}
    task_names = resolved_task_names([task for _, task in all_tasks])
    eval_epochs = resolve_epochs(epochs)
    root = listing_root(log_dir)

    async def merge_all() -> bool:
        limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_SHARD_SETS)

        async def identify(shards_dir: str) -> _ShardSet | None:
            async with limiter:
                with _shard_set_refusal(shards_dir):
                    return await _identify_shard_set(fs, shards_dir, by_name, all_tasks)

        async with AsyncFilesystem() as fs:
            found = [
                shard_set
                for shard_set in await tg_collect(
                    [functools.partial(identify, s) for s in shard_sets]
                )
                if shard_set is not None
            ]
        _check_distinct_task_ids(found, logs)

        merges: list[tuple[_ShardSet, list[str | int]]] = []
        for shard_set in found:
            retries = [
                log
                for log in logs
                if log.header.eval.shards is None
                and log.header.eval.task_id == shard_set.task_id
                and log.info.name != shard_set.merged
            ]
            if retries:
                _check_no_newer_shards(shard_set, retries, log_files, root)
                logger.info(
                    f"Not merging {_display(shard_set.shards_dir)}: the eval set "
                    "continues from its unsharded retries."
                )
                continue
            task = shard_set.task.task
            ids = selected_sample_ids(
                task.dataset, limit, sample_id, task.name, task_names
            )
            if not ids:
                raise PrerequisiteError(
                    f"[bold]ERROR[/bold]: The eval set selects no samples of "
                    f"task '{task.name}', while "
                    f"{_display(shard_set.shards_dir)} holds its shards. "
                    "Include the task's samples in sample_id (or drop the "
                    "selection), remove the task from the eval set, or move "
                    f"{_display(shard_set.merged)} and "
                    f"{_display(shard_set.shards_dir)} out of the log directory."
                )
            merges.append((shard_set, ids))

        async def merge(shard_set: _ShardSet, ids: list[str | int]) -> bool:
            task = shard_set.task.task
            if eval_epochs is not None:
                task = task_with(
                    copy.copy(task), epochs=resolve_task_epochs(task, eval_epochs)
                )
            async with limiter:
                with _shard_set_refusal(shard_set.shards_dir):
                    result = await merge_eval_log_shards_async(
                        native_path(shard_set.merged),
                        task,
                        sample_ids=ids,
                        allow_incomplete=True,
                    )
            return result.written

        written = await tg_collect([functools.partial(merge, *m) for m in merges])
        return any(written)

    return run_coroutine(merge_all())


async def _identify_shard_set(
    fs: AsyncFilesystem,
    shards_dir: str,
    by_name: dict[str, Log],
    all_tasks: list[tuple[str, ResolvedTask]],
) -> _ShardSet | None:
    """Find the task of a shard set from one of its headers.

    Uses the merged log's header when the merged log is listed, else reads
    that of the first shard's current attempt. Listed local names are
    `file://` plus the native path, not percent-encoded, so the shard set is
    listed by its native path. Any attempt would do: the
    merge refuses shards whose identifiers differ.

    Raises:
        PrerequisiteError: The shard set has neither a merged log nor an
            attempt, only stray files.
    """
    merged = eval_log_for_shards_dir(shards_dir)
    merged_log = by_name.get(merged)
    if merged_log is not None:
        header = merged_log.header
        task_id = header.eval.task_id
    else:
        listing = await list_shard_set(fs, native_path(shards_dir))
        attempt = next(
            (shard.current for shard in listing.shards if shard.current is not None),
            None,
        )
        if attempt is None:
            stray = "; ".join(
                f"{_display(file.path)} ({file.reason})" for file in listing.stray
            )
            raise PrerequisiteError(
                f"[bold]ERROR[/bold]: {_display(shards_dir)} holds no shard logs, only "
                f"log files that are not shard attempts: {stray}. "
                "Move or remove them, then re-run."
            )
        header = await read_eval_log_async(attempt.name, header_only=True)
        task_id = merged_log_task_id(
            log_basename(merged), task=header.eval.task, model=header.eval.model
        )
    identifier = task_identifier(header, None)
    task = next((task for id, task in all_tasks if id == identifier), None)
    if task is None:
        logger.warning(
            f"Not merging {_display(shards_dir)}: its shards are not associated "
            "with a task passed to eval_set."
        )
        return None
    return _ShardSet(
        shards_dir=shards_dir,
        merged=merged,
        header=header,
        task_id=task_id,
        identifier=identifier,
        task=task,
    )


def _check_distinct_task_ids(shard_sets: list[_ShardSet], logs: list[Log]) -> None:
    """Refuse a shard set whose task id another task's log or shard set has.

    The eval set pairs logs, finds retries and cleans up by task id. A merged
    log's task id comes from its file name (see `merged_log_task_id()`), so
    shard sets of different tasks with the same name in different directories
    (one per model, say) get the same task id and would be taken for attempts
    of one task.

    Raises:
        PrerequisiteError: A log or another shard set has the shard set's
            task id and a different task identifier.
    """
    for shard_set in shard_sets:
        others = [
            _display(other.shards_dir)
            for other in shard_sets
            if other.task_id == shard_set.task_id
            and other.identifier != shard_set.identifier
        ] + [
            _display(log.info.name)
            for log in logs
            if log.header.eval.task_id == shard_set.task_id
            and log.task_identifier != shard_set.identifier
        ]
        if others:
            raise PrerequisiteError(
                f"[bold]ERROR[/bold]: {_display(shard_set.shards_dir)} and "
                f"{', '.join(others)} belong to different tasks but have the same "
                f"task id ({shard_set.task_id}), so the eval set would take them "
                "for attempts of one task. Move one of them, with its merged log, "
                "to a log directory of its own, then re-run."
            )


def _check_no_newer_shards(
    shard_set: _ShardSet, retries: list[Log], log_files: list[EvalLogInfo], root: str
) -> None:
    """Refuse a shard set that holds an attempt newer than its unsharded retries.

    The retries were seeded from the merged log, and the eval set continues
    from them without merging again, so a shard added or changed after them
    would be ignored. Decision: Ransom, 2026-11-17. A tag or metadata edit
    of an existing shard also makes it newer, so the error does not say the
    files are new or advise deleting them.

    Raises:
        PrerequisiteError: A log file in the shard set is newer (by mtime)
            than the newest retry.
    """
    newest = max(retries, key=lambda log: log.info.mtime or 0)
    newer = [
        info
        for info in log_files
        if shard_companion(root, info.name) == shard_set.shards_dir
        and (info.mtime or 0) > (newest.info.mtime or 0)
    ]
    if newer:
        raise PrerequisiteError(
            f"[bold]ERROR[/bold]: {_display(shard_set.shards_dir)} holds shard "
            f"logs written or modified after the unsharded retry of its task "
            f"({_display(newest.info.name)}): "
            f"{', '.join(_display(info.name) for info in newer)}. The eval set "
            "continues from the retry and does not merge the shards again. To "
            f"continue from the retry, move {_display(shard_set.shards_dir)} "
            f"out of the log directory, with {_display(shard_set.merged)} if "
            "it is there. To merge the shards again, move the task's unsharded "
            "retries out of the log directory. Then re-run."
        )


@contextlib.contextmanager
def _shard_set_refusal(shards_dir: str) -> Iterator[None]:
    """Re-raise an exception from a shard set's startup merge as a `PrerequisiteError`.

    The message names the shards directory, the cause and what to do next;
    the original exception is the cause. Cancellation propagates unchanged.
    """
    try:
        yield
    except PrerequisiteError:
        raise
    except Exception as ex:
        if isinstance(ex, ShardSelectionError):
            advice = (
                "The eval set's selection is narrower than what the shards hold. "
                "Widen sample_id or limit to include every sharded sample (or drop "
                "the selection to run the whole dataset), remove the task from the "
                f"eval set, or move {_display(eval_log_for_shards_dir(shards_dir))} "
                f"and {_display(shards_dir)} out of the log directory. If the ids "
                "are not ones the run should hold, remove the shard named as "
                "holding them. Then re-run."
            )
        elif isinstance(ex, ShardSetError):
            advice = "Fix the files the message names, then re-run."
        elif isinstance(ex, WriteConflictError):
            advice = (
                "Re-run once the other merge has finished. If no merge is running, "
                "delete the lock file the message names and re-run."
            )
        else:
            advice = "Fix the cause, then re-run."
        raise PrerequisiteError(
            f"[bold]ERROR[/bold]: eval_set() could not merge the shards in "
            f"{_display(shards_dir)}: {escape(str(ex))}\n\n{advice}"
        ) from ex


def _display(location: str) -> str:
    """A listed location for a message: a local path for a `file://` URI."""
    return escape(native_path(location))
