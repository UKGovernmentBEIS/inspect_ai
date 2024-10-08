from typing_extensions import override

from .json import JSONRecorder


class EvalRecorder(JSONRecorder):
    @override
    @classmethod
    def handles_location(cls, location: str) -> bool:
        return location.endswith(".eval")

    @override
    def __init__(self, log_dir: str):
        super().__init__(log_dir, ".eval")
