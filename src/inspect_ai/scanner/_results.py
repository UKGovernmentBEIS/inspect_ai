from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from inspect_ai._util._async import run_coroutine

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class ScanResults:
    scan_id: str
    scan_name: str
    scanners: dict[str, "pd.DataFrame"]


def scan_results(scans_dir: str, scan_id: str) -> ScanResults:
    return run_coroutine(scan_results_async(scans_dir, scan_id))


async def scan_results_async(scans_dir: str, scan_id: str) -> ScanResults:
    return ScanResults("", "", {})


def scanner_results(scans_dir: str, scan_id: str, scanner_name: str) -> "pd.DataFrame":
    return run_coroutine(scanner_results_async(scans_dir, scan_id, scanner_name))


async def scanner_results_async(
    scans_dir: str, scan_id: str, scanner_name: str
) -> "pd.DataFrame":
    return pd.DataFrame()


async def scan_compact(scans_dir: str, scan_id: str) -> None:
    pass
