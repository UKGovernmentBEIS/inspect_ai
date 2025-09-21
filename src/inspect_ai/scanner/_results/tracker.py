from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, Sequence, cast

from inspect_ai.scanner._transcript.transcripts import Transcripts

from .._scanner.result import Result
from .._scanner.scanner import Scanner
from .._transcript.types import TranscriptInfo

if TYPE_CHECKING:
    import pandas as pd


class Reporter(Protocol):
    async def __call__(self, result: Sequence[Result]) -> None: ...


class Tracker(Protocol):
    async def __call__(
        self, transcript: TranscriptInfo, scanner: str
    ) -> Reporter | None: ...


@dataclass
class ScanOptions:
    scan_id: str
    scan_name: str
    scans_dir: str
    transcripts: Transcripts
    scanners: dict[str, Scanner[Any]]


def results_tracker(options: ScanOptions) -> Tracker:
    # create the results directory

    # create the metadata file for the scan (transcript query + scanners w/ args to reconstruct them)

    async def tracker(transcript: TranscriptInfo, scanner: str) -> Reporter | None:
        # check if we already have this transcript/scanner pair recorded

        async def report(result: Sequence[Result]) -> None:
            pass

        return report

    return tracker


def scan_options(scan_dir: str) -> ScanOptions | None:
    return cast(ScanOptions, None)


@dataclass
class ScanResults:
    scan_id: str
    scan_name: str
    scanners: dict[str, "pd.DataFrame"]


async def scan_results(
    scans_dir: str, scan_id: str, compact: bool = False
) -> ScanResults:
    return ScanResults("", "", {})
