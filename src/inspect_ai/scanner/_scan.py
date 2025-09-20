from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any, Sequence

from inspect_ai._util._async import run_coroutine

from ._scanner.scanner import Scanner
from ._transcript.transcripts import Transcripts

if TYPE_CHECKING:
    import pandas as pd


def scan(
    transcripts: Transcripts,
    scanners: Sequence[Scanner[Any] | tuple[str, Scanner[Any]]],
    name: str | None = None,
    scans_dir: str | None = None,
) -> dict[str, "pd.DataFrame"]:
    return run_coroutine(
        scan_async(
            transcripts=transcripts, scanners=scanners, name=name, scans_dir=scans_dir
        )
    )


async def scan_async(
    transcripts: Transcripts,
    scanners: Sequence[Scanner[Any] | tuple[str, Scanner[Any]]],
    name: str | None = None,
    scans_dir: str | None = None,
) -> dict[str, "pd.DataFrame"]:
    # validate and resolve name
    if name is not None:
        if not re.match(r"^[a-zA-Z0-9_-]+$", name):
            raise ValueError(
                "scan 'name' may use only letters, numbers, underscores, and dashes"
            )
    name = name or "scan"

    # resolve scans_dir
    scans_dir = scans_dir or os.getenv("INSPECT_SCANS_DIR", "./scans")

    # confirm each scanner has a unique name

    return {}
