import os
import re

from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from shortuuid import uuid
from upath import UPath

from inspect_ai._util._async import run_coroutine
from inspect_ai.scanner._scandef import ScanDef

from ._options import ScanOptions, read_scan_options
from ._reporter import scan_reporter
from ._results import ScanResults
from ._transcript.transcripts import Transcripts
from ._transcript.types import TranscriptContent


def scan(
    scandef: ScanDef,
    scan_id: str | None = None,
    scans_dir: str | None = None,
) -> ScanResults:
    return run_coroutine(
        scan_async(
            scandef=scandef,
            scan_id=scan_id,
            scans_dir=scans_dir,
        )
    )


async def scan_async(
    scandef: ScanDef,
    transcripts: Transcripts | None = None,
    scan_id: str | None = None,
    scans_dir: str | None = None,
) -> ScanResults:
    # resolve id
    scan_id = scan_id or uuid()

    # validate name
    # TODO: move this earlier?
    print(scandef.name)
    if not re.match(r"^[a-zA-Z0-9-]+$", scandef.name):
        raise ValueError("scan 'name' may use only letters, numbers, and dashes")

    # resolve transcripts
    transcripts = transcripts or scandef.transcripts
    if transcripts is None:
        raise ValueError("No 'transcripts' specified for scan.")

    # resolve scans_dir
    scans_dir = scans_dir or str(os.getenv("INSPECT_SCANS_DIR", "./scans"))

    return await _scan_async(
        UPath(scans_dir),
        ScanOptions(
            scan_id=scan_id,
            scan_name=scandef.name,
            transcripts=transcripts,
            scanners=scandef.scanners,
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
    async with options.transcripts:
        reporter, complete = await scan_reporter(scans_dir, options)
        with Progress(
            TextColumn("Scanning"),
            BarColumn(),
            TimeElapsedColumn(),
            transient=True,
        ) as progress:
            total_ticks = (await options.transcripts.count()) * len(options.scanners)
            task_id = progress.add_task("Scan", total=total_ticks)

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

                    # tick progress
                    progress.update(task_id, advance=1)

    # read all scan results for this scan
    return await complete()
