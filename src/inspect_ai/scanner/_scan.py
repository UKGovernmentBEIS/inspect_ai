from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Sequence

from shortuuid import uuid

from inspect_ai._util._async import run_coroutine
from inspect_ai._util.registry import registry_info

from ._scanner.scanner import Scanner
from ._transcript.transcripts import Transcripts

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class ScanResults:
    scan_id: str
    scan_name: str
    scanners: dict[str, "pd.DataFrame"]


def scan(
    transcripts: Transcripts,
    scanners: Sequence[Scanner[Any] | tuple[str, Scanner[Any]]],
    scan_id: str | None = None,
    scan_name: str | None = None,
    scans_dir: str | None = None,
) -> ScanResults:
    return run_coroutine(
        scan_async(
            transcripts=transcripts,
            scanners=scanners,
            scan_id=scan_id,
            scan_name=scan_name,
            scans_dir=scans_dir,
        )
    )


async def scan_async(
    transcripts: Transcripts,
    scanners: Sequence[Scanner[Any] | tuple[str, Scanner[Any]]],
    scan_id: str | None = None,
    scan_name: str | None = None,
    scans_dir: str | None = None,
) -> ScanResults:
    # resolve id
    scan_id = scan_id or uuid()

    # validate and resolve name
    if scan_name is not None:
        if not re.match(r"^[a-zA-Z0-9_-]+$", scan_name):
            raise ValueError(
                "scan 'name' may use only letters, numbers, underscores, and dashes"
            )
    scan_name = scan_name or "scan"

    # resolve scans_dir
    scans_dir = scans_dir or os.getenv("INSPECT_SCANS_DIR", "./scans")

    # resolve scanners and confirm unique names
    named_scanners: dict[str, Scanner[Any]] = {}
    for scanner in scanners:
        if isinstance(scanner, tuple):
            name, scanner = scanner
        else:
            name = registry_info(scanner).name
        if name in named_scanners:
            raise ValueError(
                f"Scanners must have unique names (found duplicate name '{name}'). Use a tuple of str,Scanner to explicitly name a scanner."
            )
        named_scanners[name] = scanner

    return ScanResults(scan_id=scan_id, scan_name=scan_name, scanners={})
