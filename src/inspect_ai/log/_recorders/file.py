import os
from logging import getLogger
from typing import Any

from typing_extensions import override

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import MODEL_NONE
from inspect_ai._util.file import clean_filename_component, filesystem
from inspect_ai._util.task import task_display_name
from inspect_ai.dataset._util import normalise_sample_id

from .._log import EvalLog, EvalSample, EvalSampleSummary, EvalSpec
from .recorder import Recorder

logger = getLogger(__name__)


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
    ) -> EvalSample:
        # establish the log to read from (might be cached)
        eval_log = await cls._log_file_maybe_cached(location)

        # throw if no samples
        if not eval_log.samples:
            raise IndexError(f"No samples found in log {location}")

        # find the sample
        id = normalise_sample_id(id) if id is not None else id
        eval_sample = next(
            (
                sample
                for sample in (eval_log.samples)
                if (
                    id
                    and normalise_sample_id(sample.id) == id
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
    async def read_log_sample_summaries(
        cls, location: str, async_fs: AsyncFilesystem | None = None
    ) -> list[EvalSampleSummary]:
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
