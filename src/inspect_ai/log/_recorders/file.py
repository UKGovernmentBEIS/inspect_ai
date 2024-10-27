from typing import Any

from typing_extensions import override

from inspect_ai._util.file import (
    filesystem,
)
from inspect_ai._util.registry import registry_unqualified_name

from .._log import EvalLog, EvalSample, EvalSpec
from .recorder import Recorder


class FileRecorder(Recorder):
    __last_read_sample_log: tuple[str, EvalLog] | None = None

    def __init__(
        self, log_dir: str, suffix: str, fs_options: dict[str, Any] = {}
    ) -> None:
        self.log_dir = log_dir.rstrip("/\\")
        self.fs = filesystem(log_dir, fs_options)
        self.fs.mkdir(self.log_dir, exist_ok=True)
        self.suffix = suffix

    def is_local(self) -> bool:
        return self.fs.is_local()

    @override
    @classmethod
    def read_log_sample(
        cls, location: str, id: str | int, epoch: int = 1
    ) -> EvalSample:
        # establish the log to read from (might be cached)
        if cls.__last_read_sample_log and (cls.__last_read_sample_log[0] == "location"):
            eval_log = cls.__last_read_sample_log[1]
        else:
            eval_log = cls.read_log(location)
            cls.__last_read_sample_log = (location, eval_log)

        # throw if no samples
        if not eval_log.samples:
            raise ValueError(f"No samples found in log {location}")

        # find the sample
        eval_sample = next(
            (
                sample
                for sample in (eval_log.samples)
                if sample.id == id and sample.epoch == epoch
            ),
            None,
        )
        if eval_sample is None:
            raise ValueError(
                f"Sample id {id} for epoch {epoch} not found in log {location}"
            )
        else:
            return eval_sample

    def _log_file_key(self, eval: EvalSpec) -> str:
        # clean underscores, slashes, and : from the log file key (so we can reliably parse it
        # later without worrying about underscores)
        def clean(s: str) -> str:
            return s.replace("_", "-").replace("/", "-").replace(":", "-")

        # remove package from task name
        task = registry_unqualified_name(eval.task)

        return f"{clean(eval.created)}_{clean(task)}_{clean(eval.task_id)}"

    def _log_file_path(self, eval: EvalSpec) -> str:
        return f"{self.log_dir}{self.fs.sep}{self._log_file_key(eval)}{self.suffix}"
