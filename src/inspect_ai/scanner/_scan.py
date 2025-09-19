from __future__ import annotations

from typing import TYPE_CHECKING, Any

from inspect_ai._util._async import run_coroutine

from ._results.options import ResultsOptions
from ._scanner.scanner import Scanner
from ._transcript.transcripts import Transcripts

if TYPE_CHECKING:
    import pandas as pd


def scan(
    transcripts: Transcripts,
    scanners: list[Scanner[Any]],
    results: ResultsOptions | None = None,
) -> dict[str, "pd.DataFrame"]:
    return run_coroutine(scan_async(transcripts, scanners, results=results))


async def scan_async(
    transcripts: Transcripts,
    scanners: list[Scanner[Any]],
    results: ResultsOptions | None = None,
) -> dict[str, "pd.DataFrame"]:
    if results is None:
        results = ResultsOptions()
    return {}
