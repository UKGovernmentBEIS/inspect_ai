from typing import Protocol, Sequence

from upath import UPath

from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.file import clean_filename_component

from ._options import ScanOptions, write_scan_options
from ._scanner.result import Result
from ._transcript.types import TranscriptInfo


class ScanReport(Protocol):
    async def __call__(self, results: Sequence[Result]) -> None: ...


class ScanReporter(Protocol):
    async def __call__(
        self, transcript: TranscriptInfo, scanner: str
    ) -> ScanReport | None: ...


async def scan_reporter(scans_dir: UPath, options: ScanOptions) -> ScanReporter:
    # create the scan dir and write the options
    scan_dir = await ensure_scan_dir(scans_dir, options.scan_id, options.scan_name)
    await write_scan_options(scan_dir, options)

    async def tracker(transcript: TranscriptInfo, scanner: str) -> ScanReport | None:
        # check if we already have this transcript/scanner pair recorded

        async def report(results: Sequence[Result]) -> None:
            pass

        return report

    return tracker


async def ensure_scan_dir(scans_dir: UPath, scan_id: str, scan_name: str) -> UPath:
    # look for an existing scan dir
    scan_dir: UPath | None = None
    ensure_scans_dir(scans_dir)
    for f in scans_dir.glob(f"*_{scan_id}"):
        if f.is_dir():
            scan_dir = f
            break

    # if there is no scan_dir then create one
    if scan_dir is None:
        scan_dir = (
            scans_dir / f"{clean_filename_component(iso_now())}_{scan_name}_{scan_id}"
        )
        scan_dir.mkdir(parents=True, exist_ok=False)

    # return scan dir
    return scan_dir


def ensure_scans_dir(scans_dir: UPath) -> None:
    scans_dir.mkdir(parents=True, exist_ok=True)
