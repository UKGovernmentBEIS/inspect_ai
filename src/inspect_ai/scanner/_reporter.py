from typing import Protocol, Sequence

from upath import UPath

from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.file import clean_filename_component

from ._options import ScanOptions, write_scan_options
from ._scanner.result import Result
from ._transcript.types import TranscriptInfo


class ScanReport(Protocol):
    async def __call__(self, results: Sequence[Result]) -> None: ...


class ScanReporter(Protocol):
    async def __call__(
        self, transcript: TranscriptInfo, scanner: str
    ) -> ScanReport | None: ...


async def scan_reporter(scans_dir: UPath, options: ScanOptions) -> ScanReporter:
    import pandas as pd
    import pyarrow as pa

    from inspect_ai.analysis._dataframe.util import arrow_types_mapper

    # create the scan dir and write the options
    scan_dir = ensure_scan_dir(scans_dir, options.scan_id, options.scan_name)
    await write_scan_options(scan_dir, options)

    async def tracker(transcript: TranscriptInfo, scanner: str) -> ScanReport | None:
        # check if we already have this transcript/scanner pair recorded
        scan_file = scan_dir / f"{transcript.id}_{scanner}.parquet"
        if scan_file.exists():
            return None

        async def report(results: Sequence[Result]) -> None:
            # create records
            records = [
                dict(
                    transcript_id=transcript.id,
                    transcript_source=transcript.source,
                )
                | result.model_dump()
                for result in results
            ]

            # convert to arrow-typed dataframe and write to parquet
            df = pd.DataFrame(records)
            table = pa.Table.from_pandas(df)
            df_arrow = table.to_pandas(types_mapper=arrow_types_mapper)
            df_arrow.to_parquet(str(scan_file))

        return report

    return tracker


async def scan_compact(scans_dir: UPath, scan_id: str) -> None:
    from collections import defaultdict

    import pandas as pd
    import pyarrow as pa

    from inspect_ai.analysis._dataframe.util import arrow_types_mapper

    # determine scan_dir
    scan_dir = find_scan_dir(scans_dir, scan_id)
    if scan_dir is None:
        raise ValueError(f"Scan id '{scan_id}' not found in scans dir 'scans_dir'.")

    # group parquet files by scanner name
    scanner_files = defaultdict(list)
    for parquet_file in scan_dir.glob("*.parquet"):
        # parse filename: {transcript_id}_{scanner_name}.parquet
        parts = parquet_file.stem.rsplit("_", 1)
        if len(parts) == 2:
            transcript_id, scanner_name = parts
            scanner_files[scanner_name].append(parquet_file)

    # consolidate files for each scanner
    for scanner_name, files in scanner_files.items():
        # read all parquet files for this scanner
        dfs = []
        for file in files:
            df = pd.read_parquet(str(file))
            dfs.append(df)

        # concatenate all dataframes
        consolidated_df = pd.concat(dfs, ignore_index=True)

        # convert to arrow table and back to ensure consistent types
        table = pa.Table.from_pandas(consolidated_df)
        df_arrow = table.to_pandas(types_mapper=arrow_types_mapper)

        # write consolidated file
        consolidated_file = scan_dir / f"{scanner_name}.parquet"
        df_arrow.to_parquet(str(consolidated_file))

        # delete original files
        for file in files:
            file.unlink()


def ensure_scan_dir(scans_dir: UPath, scan_id: str, scan_name: str) -> UPath:
    # look for an existing scan dir
    scan_dir: UPath | None = None
    ensure_scans_dir(scans_dir)
    for f in scans_dir.glob(f"*_{scan_id}"):
        if f.is_dir():
            scan_dir = f
            break

    # if there is no scan_dir then create one
    if scan_dir is None:
        scan_dir = (
            scans_dir / f"{clean_filename_component(iso_now())}_{scan_name}_{scan_id}"
        )
        scan_dir.mkdir(parents=True, exist_ok=False)

    # return scan dir
    return scan_dir


def find_scan_dir(scans_dir: UPath, scan_id: str) -> UPath | None:
    ensure_scans_dir(scans_dir)
    for f in scans_dir.glob(f"*_{scan_id}"):
        if f.is_dir():
            return f

    return None


def ensure_scans_dir(scans_dir: UPath) -> None:
    scans_dir.mkdir(parents=True, exist_ok=True)
