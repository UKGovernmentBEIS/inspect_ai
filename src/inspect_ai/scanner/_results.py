from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

from upath import UPath

from inspect_ai._util._async import run_coroutine

from ._reporter import find_scan_dir

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class ScanResults:
    scan_id: str
    scan_name: str
    scanners: dict[str, "pd.DataFrame"]


# Sync overloads
@overload
def scan_results(scans_dir: str, scan_id: str) -> ScanResults: ...


@overload
def scan_results(scans_dir: str, scan_id: str, scanner_name: str) -> "pd.DataFrame": ...


def scan_results(
    scans_dir: str, scan_id: str, scanner_name: str | None = None
) -> ScanResults | "pd.DataFrame":
    """Get scan results.

    Args:
        scans_dir: Directory containing scan results
        scan_id: ID of the scan
        scanner_name: Optional name of specific scanner to get results for

    Returns:
        If scanner_name is provided, returns DataFrame with scanner results.
        Otherwise, returns ScanResults with all scanner results.
    """
    if scanner_name is not None:
        return run_coroutine(scan_results_async(scans_dir, scan_id, scanner_name))
    else:
        return run_coroutine(scan_results_async(scans_dir, scan_id))


# Async overloads
@overload
async def scan_results_async(scans_dir: str, scan_id: str) -> ScanResults: ...


@overload
async def scan_results_async(
    scans_dir: str, scan_id: str, scanner_name: str
) -> "pd.DataFrame": ...


async def scan_results_async(
    scans_dir: str, scan_id: str, scanner_name: str | None = None
) -> ScanResults | "pd.DataFrame":
    """Get scan results asynchronously.

    Args:
        scans_dir: Directory containing scan results
        scan_id: ID of the scan
        scanner_name: Optional name of specific scanner to get results for

    Returns:
        If scanner_name is provided, returns DataFrame with scanner results.
        Otherwise, returns ScanResults with all scanner results.
    """
    # determine the scan dir
    scan_dir = find_scan_dir(UPath(scans_dir), scan_id)
    if scan_dir is None:
        raise ValueError(f"Scan id '{scan_id}' not found in scans dir '{scans_dir}'.")

    if scanner_name is not None:
        # Return specific scanner results
        import pandas as pd

        return pd.DataFrame()
    else:
        # Return all scan results
        return ScanResults("", "", {})
