from typing import Protocol, Sequence

from ._options import ScanOptions
from ._scanner.result import Result
from ._transcript.types import TranscriptInfo


class ResultsReporter(Protocol):
    async def __call__(self, results: Sequence[Result]) -> None: ...


class ResultsTracker(Protocol):
    async def __call__(
        self, transcript: TranscriptInfo, scanner: str
    ) -> ResultsReporter | None: ...


def results_tracker(options: ScanOptions) -> ResultsTracker:
    # create the results directory

    # create the metadata file for the scan (transcript query + scanners w/ args to reconstruct them)

    async def tracker(
        transcript: TranscriptInfo, scanner: str
    ) -> ResultsReporter | None:
        # check if we already have this transcript/scanner pair recorded

        async def report(results: Sequence[Result]) -> None:
            pass

        return report

    return tracker
