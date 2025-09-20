from typing import Protocol

from inspect_ai.scanner._transcript.types import TranscriptInfo

from .._scanner.result import Result


class ResultReporter(Protocol):
    async def __call__(self, result: Result) -> None: ...


class ResultsTracker(Protocol):
    async def __call__(
        self, transcript: TranscriptInfo, scanner: str, context_id: str | None
    ) -> ResultReporter | None: ...


def results_tracker(scans_dir: str, scan_id: str, scan_name: str) -> ResultsTracker:
    # create the results directory

    # create the metadata file for the scan (transcript query + scanners w/ args to reconstruct them)

    async def tracker(
        transcript: TranscriptInfo, scanner: str, context_id: str | None
    ) -> ResultReporter | None:
        async def report(result: Result) -> None:
            pass

        return report

    return tracker
