from inspect_ai._util._async import run_coroutine

from ._recorder.factory import scan_recorder_type_for_location
from ._recorder.recorder import ScanInfo, ScanResults


def scan_info(scan_location: str) -> ScanInfo:
    return run_coroutine(scan_info_async(scan_location))


async def scan_info_async(scan_location: str) -> ScanInfo:
    recorder = scan_recorder_type_for_location(scan_location)
    return await recorder.info(scan_location)


def scan_results(
    scan_location: str | ScanInfo, scanner: str | None = None
) -> ScanResults:
    return run_coroutine(scan_results_async(scan_location, scanner))


async def scan_results_async(
    scan_location: str | ScanInfo, scanner: str | None = None
) -> ScanResults:
    scan_location = (
        scan_location.location if isinstance(scan_location, ScanInfo) else scan_location
    )
    recorder = scan_recorder_type_for_location(scan_location)
    return await recorder.results(scan_location, scanner)
