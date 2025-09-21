from dataclasses import dataclass
from typing import Any, cast

from ._scanner.scanner import Scanner
from ._transcript.transcripts import Transcripts


@dataclass
class ScanOptions:
    scan_id: str
    scan_name: str
    scans_dir: str
    transcripts: Transcripts
    scanners: dict[str, Scanner[Any]]


async def read_scan_options(scan_dir: str) -> ScanOptions | None:
    return cast(ScanOptions, None)


async def write_scan_options(options: ScanOptions) -> None:
    pass
