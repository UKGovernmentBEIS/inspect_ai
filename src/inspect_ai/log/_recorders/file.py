from typing import Any

from inspect_ai._util.file import (
    filesystem,
)
from inspect_ai._util.registry import registry_unqualified_name

from .._log import EvalSpec
from .recorder import Recorder


class FileRecorder(Recorder):
    def __init__(
        self, log_dir: str, suffix: str, fs_options: dict[str, Any] = {}
    ) -> None:
        self.log_dir = log_dir.rstrip("/\\")
        self.fs = filesystem(log_dir, fs_options)
        self.fs.mkdir(self.log_dir, exist_ok=True)
        self.suffix = suffix

    def is_local(self) -> bool:
        return self.fs.is_local()

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
