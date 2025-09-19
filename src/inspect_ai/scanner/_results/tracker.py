from typing import Protocol

from inspect_ai.scanner._transcript.types import TranscriptInfo

from .._scanner.result import Result
from .options import ResultsOptions


class ResultsTracker(Protocol):
    async def __call__(
        self, transcript: TranscriptInfo, scanner: str, result: Result
    ) -> None: ...


def results_tracker(
    scan_id: str, scan_name: str, options: ResultsOptions
) -> ResultsTracker:
    # create the sqlite database for this

    async def track(transcript: TranscriptInfo, scanner: str, result: Result) -> None:
        pass

    return track
