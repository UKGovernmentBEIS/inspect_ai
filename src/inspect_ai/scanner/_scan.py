import os
import re
from typing import Any, Sequence

from shortuuid import uuid
from upath import UPath

from inspect_ai._util._async import run_coroutine
from inspect_ai._util.registry import registry_info

from ._options import ScanOptions, read_scan_options
from ._reporter import scan_compact, scan_reporter
from ._results import ScanResults, scan_results_async
from ._scanner.scanner import Scanner
from ._transcript.transcripts import Transcripts
from ._transcript.types import TranscriptContent


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
        if not re.match(r"^[a-zA-Z0-9-]+$", scan_name):
            raise ValueError("scan 'name' may use only letters, numbers, and dashes")
    scan_name = scan_name or "scan"

    # resolve scans_dir
    scans_dir = scans_dir or str(os.getenv("INSPECT_SCANS_DIR", "./scans"))

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

    return await _scan_async(
        UPath(scans_dir),
        ScanOptions(
            scan_id=scan_id,
            scan_name=scan_name,
            transcripts=transcripts,
            scanners=named_scanners,
        ),
    )


async def scan_resume(
    scan_dir: str,
) -> ScanResults:
    return run_coroutine(scan_resume_async(scan_dir))


async def scan_resume_async(
    scan_dir: str,
) -> ScanResults:
    scan_dir_path = UPath(scan_dir)
    scans_dir = UPath(scan_dir).parent
    options = await read_scan_options(scan_dir_path)
    if options is None:
        raise RuntimeError(
            f"The specified directory '{scan_dir}' does not contain a scan."
        )
    return await _scan_async(scans_dir, options)


async def _scan_async(scans_dir: UPath, options: ScanOptions) -> ScanResults:
    # naive scan with:
    #  No parallelism
    #  No content filtering
    #  Supporting only Transcript

    # set up our reporter (stores results and lets us skip results we already have)
    reporter = await scan_reporter(scans_dir, options)

    # read transcripts from index and process them if required
    async with options.transcripts:
        for t in await options.transcripts.index():
            for name, scanner in options.scanners.items():
                # get reporter for this transcript/scanner (if None we already did this work)
                report = await reporter(t, name)
                if report is None:
                    continue

                # read the transcript
                transcript = await options.transcripts.read(
                    t, TranscriptContent(messages="all")
                )

                # call the scanner (note that later this may accumulate multiple
                # scanner calls e.g. for ChatMessage scanners and then report all
                # of the results together)
                result = await scanner(transcript)

                # report the result
                if result is not None:
                    await report([result])

    # read all scan results for this scan
    await scan_compact(scans_dir, options.scan_id)
    return await scan_results_async(scans_dir.as_posix(), options.scan_id)
