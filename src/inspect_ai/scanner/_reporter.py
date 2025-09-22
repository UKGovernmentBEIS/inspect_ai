from dataclasses import dataclass
from typing import Any, Protocol, Sequence, cast

from upath import UPath

from ._scanner.result import Result
from ._scanner.scanner import Scanner
from ._transcript.transcripts import Transcripts
from ._transcript.types import TranscriptInfo


@dataclass
class ScanOptions:
    scan_id: str
    scan_name: str
    transcripts: Transcripts
    scanners: dict[str, Scanner[Any]]


class ScanReport(Protocol):
    async def __call__(self, results: Sequence[Result]) -> None: ...


class ScanReporter(Protocol):
    async def __call__(
        self, transcript: TranscriptInfo, scanner: str
    ) -> ScanReport | None: ...


async def scan_reporter(scans_dir: UPath, options: ScanOptions) -> ScanReporter:
    # initialize the scan
    scan_dir = await initialize_scan(scans_dir, options)  # noqa: F841

    async def tracker(transcript: TranscriptInfo, scanner: str) -> ScanReport | None:
        # check if we already have this transcript/scanner pair recorded

        async def report(results: Sequence[Result]) -> None:
            pass

        return report

    return tracker


async def initialize_scan(scans_dir: UPath, options: ScanOptions) -> UPath:
    return scans_dir


async def read_scan_options(scan_dir: UPath) -> ScanOptions | None:
    return cast(ScanOptions, None)
