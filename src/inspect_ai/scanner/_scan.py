from typing import Any

from inspect_ai._util._async import run_coroutine
from inspect_ai.scanner._scanner import Scanner

from ._transcript.transcripts import Transcripts


def scan(transcripts: Transcripts, scanners: list[Scanner[Any]]) -> None:
    run_coroutine(scan_async(transcripts, scanners))


async def scan_async(transcripts: Transcripts, scanners: list[Scanner[Any]]) -> None:
    pass
