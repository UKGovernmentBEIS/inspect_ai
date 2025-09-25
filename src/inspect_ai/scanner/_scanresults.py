from __future__ import annotations

from typing import TYPE_CHECKING, overload

from inspect_ai._util._async import run_coroutine
from inspect_ai.scanner._recorder.recorder import ScanResults
from inspect_ai.scanner._recorder.types import scan_recorder_type_for_location

if TYPE_CHECKING:
    import pandas as pd


# Sync overloads
@overload
def scan_results(scan_location: str) -> ScanResults: ...


@overload
def scan_results(scan_location: str, scanner_name: str) -> "pd.DataFrame": ...


def scan_results(
    scan_location: str, scanner_name: str | None = None
) -> ScanResults | "pd.DataFrame":
    if scanner_name is not None:
        return run_coroutine(scan_results_async(scan_location, scanner_name))
    else:
        return run_coroutine(scan_results_async(scan_location))


# Async overloads
@overload
async def scan_results_async(scan_location: str) -> ScanResults: ...


@overload
async def scan_results_async(
    scan_location: str, scanner_name: str
) -> "pd.DataFrame": ...


async def scan_results_async(
    scan_location: str, scanner_name: str | None = None
) -> ScanResults | "pd.DataFrame":
    recorder = scan_recorder_type_for_location(scan_location)
    results = await recorder.results(scan_location)
    if scanner_name is not None:
        return results.scanners[scanner_name]
    else:
        return results
