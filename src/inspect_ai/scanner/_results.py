from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

from upath import UPath

from inspect_ai._util._async import run_coroutine
from inspect_ai._util.path import pretty_path

if TYPE_CHECKING:
    import pandas as pd

from textwrap import dedent

from inspect_ai._util.file import file


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
    import pandas as pd

    # determine the scan dir
    scan_dir = find_scan_dir(UPath(scans_dir), scan_id)
    if scan_dir is None:
        raise ValueError(f"Scan id '{scan_id}' not found in scans dir '{scans_dir}'.")

    # check for uncompacted transcript files
    uncompacted_files = False
    for parquet_file in scan_dir.glob(".*.parquet"):
        # transcript files have format: .{transcript_id}_{scanner_name}.parquet
        uncompacted_files = True
        break

    if uncompacted_files:
        raise ValueError(
            f"Scan '{scan_id}' has uncompacted transcript files. "
            f"Run scan_resume('{pretty_path(str(scan_dir))}') to complete the scan."
        )

    # extract scan_name from directory name
    # format: {timestamp}_{scan_name}_{scan_id}
    parts = scan_dir.name.rsplit("_", 2)
    scan_name = parts[1] if len(parts) >= 3 else ""

    if scanner_name is not None:
        # Return specific scanner results
        scanner_file = scan_dir / f"{scanner_name}.parquet"
        if not scanner_file.exists():
            raise ValueError(
                f"Scanner '{scanner_name}' not found for scan id '{scan_id}'."
            )

        return pd.read_parquet(str(scanner_file))
    else:
        # Return all scan results
        scanners = {}
        for parquet_file in scan_dir.glob("*.parquet"):
            # skip any transcript-specific files (they start with .)
            if not parquet_file.stem.startswith("."):
                scanner_name = parquet_file.stem
                scanners[scanner_name] = pd.read_parquet(str(parquet_file))

        return ScanResults(scan_id, scan_name, scanners)


def find_scan_dir(scans_dir: UPath, scan_id: str) -> UPath | None:
    ensure_scans_dir(scans_dir)
    for f in scans_dir.glob(f"*_{scan_id}"):
        if f.is_dir():
            return f

    return None


def ensure_scans_dir(scans_dir: UPath) -> None:
    scans_dir.mkdir(parents=True, exist_ok=True)
    with file((scans_dir / ".gitignore").as_posix(), "w") as f:
        f.write(
            dedent("""
            .scan.json
            .*.parquet
            """)
        )
