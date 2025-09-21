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


def read_scan_options(scan_dir: str) -> ScanOptions | None:
    return cast(ScanOptions, None)


def write_scan_options(scan_dir: str) -> None:
    pass
