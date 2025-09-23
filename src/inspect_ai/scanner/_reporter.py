import functools
import io
from typing import Protocol, Sequence, cast

from upath import UPath

from inspect_ai._util._async import tg_collect
from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.file import clean_filename_component

from ._options import ScanOptions, remove_scan_options, write_scan_options
from ._results import ScanResults, find_scan_dir
from ._scanner.result import Result
from ._transcript.types import TranscriptInfo
from ._util.file import (
    delete_files_async,
    read_file_async,
    write_file_async,
)


class ScanReport(Protocol):
    async def __call__(self, results: Sequence[Result]) -> None: ...


class ScanReporter(Protocol):
    async def __call__(
        self, transcript: TranscriptInfo, scanner: str
    ) -> ScanReport | None: ...


class ScanComplete(Protocol):
    async def __call__(self) -> ScanResults: ...


async def scan_reporter(
    scans_dir: UPath, options: ScanOptions
) -> tuple[ScanReporter, ScanComplete]:
    import pandas as pd
    import pyarrow as pa

    from inspect_ai.analysis._dataframe.util import arrow_types_mapper

    # create the scan dir and write the options
    scan_dir = ensure_scan_dir(scans_dir, options.scan_id, options.scan_name)
    await write_scan_options(scan_dir, options)

    async def reporter(transcript: TranscriptInfo, scanner: str) -> ScanReport | None:
        # check if we already have this transcript/scanner pair recorded
        scan_file = scan_dir / f".{transcript.id}_{scanner}.parquet"
        if scan_file.exists():
            return None

        # check if we already have a full file for this scanner
        scanner_file = scan_dir / f"{scanner}.parquet"
        if scanner_file.exists():
            return None

        async def report(results: Sequence[Result]) -> None:
            # create records
            records = [
                cast(
                    dict[str, str | bool | int | float | None],
                    dict(
                        transcript_id=transcript.id,
                        transcript_source=transcript.source,
                    ),
                )
                | result.to_df_columns()
                for result in results
            ]

            # convert to arrow-typed dataframe and write to parquet
            df = pd.DataFrame(records)
            table = pa.Table.from_pandas(df)
            df_arrow = table.to_pandas(types_mapper=arrow_types_mapper)
            buffer = io.BytesIO()
            df_arrow.to_parquet(buffer)
            await write_file_async(str(scan_file), buffer.getvalue())

        return report

    async def complete() -> ScanResults:
        results = await _scan_compact(scan_dir, options)
        await remove_scan_options(scan_dir)
        return results

    return reporter, complete


async def _scan_compact(scan_dir: UPath, options: ScanOptions) -> ScanResults:
    from collections import defaultdict

    import pandas as pd
    import pyarrow as pa

    from inspect_ai.analysis._dataframe.util import arrow_types_mapper

    # group parquet files by scanner name
    scanner_files = defaultdict(list)
    for parquet_file in scan_dir.glob(".*.parquet"):
        # parse filename: {transcript_id}_{scanner_name}.parquet
        parts = parquet_file.stem.split("_", 1)
        _, scanner_name = parts
        scanner_files[scanner_name].append(parquet_file)

    # consolidate files for each scanner
    scanner_results: dict[str, pd.DataFrame] = {}
    for scanner_name, files in scanner_files.items():
        # skip if consolidated file already exists
        consolidated_file = scan_dir / f"{scanner_name}.parquet"
        if consolidated_file.exists():
            # just delete the transcript-specific files
            for file in files:
                file.unlink()
            continue

        # read all parquet files for this scanner
        dfs_bytes = await tg_collect(
            functools.partial(read_file_async, str(file)) for file in files
        )
        dfs = []
        for df_bytes in dfs_bytes:
            buffer = io.BytesIO(df_bytes)
            df = pd.read_parquet(buffer)
            dfs.append(df)

        # concatenate all dataframes
        consolidated_df = pd.concat(dfs, ignore_index=True)

        # convert to arrow table and back to ensure consistent types
        table = pa.Table.from_pandas(consolidated_df)
        df_arrow = table.to_pandas(types_mapper=arrow_types_mapper)
        scanner_results[scanner_name] = df_arrow

        # write consolidated file
        buffer = io.BytesIO()
        df_arrow.to_parquet(buffer)
        await write_file_async(str(consolidated_file), buffer.getvalue())

        # delete original files
        await delete_files_async([str(file) for file in files])

    return ScanResults(
        scan_id=options.scan_id, scan_name=options.scan_name, scanners=scanner_results
    )


def ensure_scan_dir(scans_dir: UPath, scan_id: str, scan_name: str) -> UPath:
    # look for an existing scan dir
    scan_dir = find_scan_dir(scans_dir, scan_id)

    # if there is no scan_dir then create one
    if scan_dir is None:
        scan_dir = (
            scans_dir / f"{clean_filename_component(iso_now())}_{scan_name}_{scan_id}"
        )
        scan_dir.mkdir(parents=True, exist_ok=False)

    # return scan dir
    return scan_dir
