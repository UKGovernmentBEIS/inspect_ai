from dataclasses import dataclass
from typing import Any, Protocol, cast

from inspect_ai.scanner._transcript.transcripts import Transcripts

from .._scanner.result import Result
from .._scanner.scanner import Scanner
from .._transcript.types import TranscriptInfo


class Reporter(Protocol):
    async def __call__(self, result: Result) -> None: ...


class Tracker(Protocol):
    async def __call__(
        self, transcript: TranscriptInfo, scanner: str, context_id: str | None
    ) -> Reporter | None: ...


def results_tracker(
    scans_dir: str,
    scan_id: str,
    scan_name: str,
    transcripts: Transcripts,
    scanners: dict[str, Scanner[Any]],
) -> Tracker:
    # create the results directory

    # create the metadata file for the scan (transcript query + scanners w/ args to reconstruct them)

    async def tracker(
        transcript: TranscriptInfo, scanner: str, context_id: str | None
    ) -> Reporter | None:
        async def report(result: Result) -> None:
            pass

        return report

    return tracker


@dataclass
class ScanOptions:
    name: str
    transcripts: Transcripts
    scanners: dict[str, Scanner[Any]]


def scan_options_from_tracker(scans_dir: str, scan_id: str) -> ScanOptions:
    return cast(ScanOptions, None)
