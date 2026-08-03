import os
from logging import getLogger
from typing import Any, Callable

import anyio.to_thread
from typing_extensions import override

from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.constants import MODEL_NONE
from inspect_ai._util.file import clean_filename_component, filesystem
from inspect_ai._util.task import task_display_name
from inspect_ai.dataset._util import normalise_sample_id

from .._log import EvalLog, EvalSample, EvalSampleSummary, EvalSpec
from .recorder import Recorder

logger = getLogger(__name__)


async def write_local_snapshot(
    location: str, fsync: bool, writer: Callable[[], None]
) -> bool:
    """Run a blocking atomic local write in a worker thread.

    The worker thread keeps the blocking write/fsync from stalling the
    event loop; the writer's atomic temp-file + rename pattern (see
    :mod:`inspect_ai._util.atomic_write`) means an interrupted write can't
    corrupt the existing log on disk (#2949).

    Shared local-write policy for the file recorders. ``fsync=False`` marks
    the write as a skippable intermediate snapshot: a ``PermissionError``
    from the atomic rename (Windows file-in-use, e.g. the viewer reading
    the log) is logged and swallowed rather than failing the task — the
    previous valid log is untouched and the next flush retries naturally.
    Final writes (``fsync=True``) always raise.

    The worker thread is not abandoned on cancellation (the anyio default):
    callers may reuse resources the writer reads (e.g. the zip temp file)
    as soon as this returns, so the thread must have finished by then.

    Args:
        location: Destination path, used in the skip warning.
        fsync: Whether this is a durable final write (True) or a skippable
            intermediate snapshot (False). The writer itself is responsible
            for actually fsync'ing (or not) accordingly — snapshots skip
            fsync since physical writeback of a large log would stall the
            worker thread for seconds per flush, and their crash-durability
            matches the pre-atomic-write behaviour (none).
        writer: Blocking callable that performs the atomic write.

    Returns:
        True if the write happened, False if it was skipped.
    """
    try:
        await anyio.to_thread.run_sync(writer)
        return True
    except PermissionError as ex:
        # On Windows os.replace() needs DELETE access on the target,
        # denied while a reader holds the log open.
        if fsync:
            raise
        logger.warning(
            f"Skipped intermediate log write for {location} "
            f"(file in use by another program): {ex}"
        )
        return False


class FileRecorder(Recorder):
    __last_read_sample_log: tuple[str, EvalLog] | None = None

    def __init__(
        self, log_dir: str, suffix: str, fs_options: dict[str, Any] | None = None
    ) -> None:
        self.log_dir = log_dir.rstrip("/\\")
        self.suffix = suffix

        # initialise filesystem
        self.fs = filesystem(log_dir, fs_options if fs_options is not None else {})
        self.fs.mkdir(self.log_dir, exist_ok=True)

    def is_local(self) -> bool:
        return self.fs.is_local()

    @override
    def is_writeable(self) -> bool:
        return self.fs.is_writeable(self.log_dir)

    @override
    @classmethod
    async def read_log_sample(
        cls,
        location: str,
        id: str | int | None = None,
        epoch: int = 1,
        uuid: str | None = None,
        exclude_fields: set[str] | None = None,
        reader: AsyncZipReader | None = None,
    ) -> EvalSample:
        # establish the log to read from (might be cached)
        eval_log = await cls._log_file_maybe_cached(location)

        # throw if no samples
        if not eval_log.samples:
            raise IndexError(f"No samples found in log {location}")

        # find the sample. Prefer an exact id match so ids that normalise alike
        # (e.g. the string "001" and the int 1, which both normalise to a
        # zero-filled "1") stay individually addressable, then fall back to the
        # normalised match for loose addressing (e.g. "1" -> int 1) and uuid.
        eval_sample: EvalSample | None = None
        if id is not None:
            eval_sample = next(
                (
                    sample
                    for sample in eval_log.samples
                    if sample.id == id and sample.epoch == epoch
                ),
                None,
            )
        if eval_sample is None:
            norm_id = normalise_sample_id(id) if id is not None else None
            eval_sample = next(
                (
                    sample
                    for sample in eval_log.samples
                    if (
                        norm_id is not None
                        and normalise_sample_id(sample.id) == norm_id
                        and sample.epoch == epoch
                    )
                    or (uuid and sample.uuid == uuid)
                ),
                None,
            )
        if eval_sample is None:
            raise IndexError(
                f"Sample id {id} for epoch {epoch} not found in log {location}"
            )
        else:
            return eval_sample

    @classmethod
    @override
    async def read_log_sample_summaries(cls, location: str) -> list[EvalSampleSummary]:
        # establish the log to read from (might be cached)
        eval_log = await cls._log_file_maybe_cached(location)
        if not eval_log.samples:
            return []
        return [sample.summary() for sample in eval_log.samples]

    @classmethod
    async def _log_file_maybe_cached(cls, location: str) -> EvalLog:
        # establish the log to read from (might be cached)
        if cls.__last_read_sample_log and (cls.__last_read_sample_log[0] == location):
            eval_log = cls.__last_read_sample_log[1]
        else:
            eval_log = await cls.read_log(location)
            cls.__last_read_sample_log = (location, eval_log)
        return eval_log

    def _log_file_key(self, eval: EvalSpec) -> str:
        # remove package from task name
        task = task_display_name(eval.task)  # noqa: F841

        # derive log file pattern
        log_file_pattern = os.getenv("INSPECT_EVAL_LOG_FILE_PATTERN", "{task}_{id}")

        # compute and return log file name
        log_file_name = f"{clean_filename_component(eval.created)}_" + log_file_pattern
        log_file_name = log_file_name.replace("{task}", clean_filename_component(task))
        log_file_name = log_file_name.replace(
            "{id}", clean_filename_component(eval.task_id)
        )
        model = clean_filename_component(eval.model) if eval.model != MODEL_NONE else ""
        log_file_name = log_file_name.replace("{model}", model)
        return log_file_name

    def _log_file_path(self, eval: EvalSpec) -> str:
        return f"{self.log_dir}{self.fs.sep}{self._log_file_key(eval)}{self.suffix}"
