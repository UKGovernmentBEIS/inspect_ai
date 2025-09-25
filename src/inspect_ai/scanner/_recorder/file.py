import functools
import io
from typing import Sequence, cast, override

from upath import UPath

from inspect_ai._util._async import tg_collect
from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.file import clean_filename_component, file, filesystem
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.path import pretty_path
from inspect_ai.analysis._dataframe.util import arrow_types_mapper
from inspect_ai.scanner._recorder.spec import ScanSpec
from inspect_ai.scanner._scanner.result import Result
from inspect_ai.scanner._transcript.types import TranscriptInfo
from inspect_ai.scanner._util.file import (
    delete_files_async,
    read_file_async,
    write_file_async,
)

from .recorder import ScanRecorder, ScanResults

SCAN_JSON = "_scan.json"


class FileRecorder(ScanRecorder):
    def __init__(self) -> None:
        self._scan_dir: UPath | None = None
        self._scan_spec: ScanSpec | None = None

    @override
    async def init(self, spec: ScanSpec, scans_location: str) -> None:
        # create the scan dir
        self._scan_dir = _ensure_scan_dir(
            UPath(scans_location), spec.scan_id, spec.scan_name
        )
        # write the spec
        with file((self.scan_dir / SCAN_JSON).as_posix(), "w") as f:
            f.write(to_json_str_safe(spec))
        # save the spec
        self._scan_spec = spec

    @override
    async def resume(self, scan_location: str) -> ScanSpec:
        self._scan_dir = UPath(scan_location)
        self._scan_spec = _read_scan_spec(self._scan_dir)
        return self._scan_spec

    @override
    async def is_recorded(self, transcript: TranscriptInfo, scanner: str) -> bool:
        # check if we already have this transcript/scanner pair recorded
        scan_file = self.scan_dir / f".{transcript.id}_{scanner}.parquet"
        if scan_file.exists():
            return True

        # check if we already have a full file for this scanner
        scanner_file = self.scan_dir / f"{scanner}.parquet"
        if scanner_file.exists():
            return True

        return False

    @override
    async def record(
        self, transcript: TranscriptInfo, scanner: str, results: Sequence[Result]
    ) -> None:
        import pandas as pd
        import pyarrow as pa

        # compute scan file name
        scan_file = self.scan_dir / f".{transcript.id}_{scanner}.parquet"

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

    @override
    async def flush(self) -> None:
        pass

    @override
    async def complete(self) -> ScanResults:
        from collections import defaultdict

        import pandas as pd
        import pyarrow as pa

        from inspect_ai.analysis._dataframe.util import arrow_types_mapper

        # group parquet files by scanner name
        scanner_files = defaultdict(list)
        for parquet_file in self.scan_dir.glob(".*.parquet"):
            # parse filename: {transcript_id}_{scanner_name}.parquet
            parts = parquet_file.stem.split("_", 1)
            _, scanner_name = parts
            scanner_files[scanner_name].append(parquet_file)

        # consolidate files for each scanner
        scanner_results: dict[str, pd.DataFrame] = {}
        for scanner_name, files in scanner_files.items():
            # skip if consolidated file already exists
            consolidated_file = self.scan_dir / f"{scanner_name}.parquet"
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
            spec=self.scan_spec,
            location=self.scan_dir.as_posix(),
            scanners=scanner_results,
        )

    @property
    def scan_dir(self) -> UPath:
        if self._scan_dir is None:
            raise RuntimeError(
                "File recorder must be initialized or resumed before use."
            )
        return self._scan_dir

    @property
    def scan_spec(self) -> ScanSpec:
        if self._scan_spec is None:
            raise RuntimeError(
                "File recorder must be initialized or resumed before use."
            )
        return self._scan_spec

    @staticmethod
    async def spec(scan_location: str) -> ScanSpec:
        return _read_scan_spec(UPath(scan_location))

    @staticmethod
    async def results(scan_location: str) -> ScanResults:
        import pandas as pd

        # read scan spec
        scan_dir = UPath(scan_location)
        spec = _read_scan_spec(scan_dir)

        # check for uncompacted transcript files
        uncompacted_files = False
        for parquet_file in scan_dir.glob(".*.parquet"):
            # transcript files have format: .{transcript_id}_{scanner_name}.parquet
            uncompacted_files = True
            break

        if uncompacted_files:
            pretty_scan_dir = pretty_path(str(scan_dir))
            raise ValueError(
                f"Scan '{pretty_scan_dir}' has uncompacted transcript files. "
                f"Run scan_resume('{pretty_scan_dir}') to complete the scan."
            )

        # read data frames
        scanners = {}
        for parquet_file in scan_dir.glob("*.parquet"):
            # skip any transcript-specific files (they start with .)
            if not parquet_file.stem.startswith("."):
                scanner_name = parquet_file.stem
                scanners[scanner_name] = pd.read_parquet(str(parquet_file))

        return ScanResults(
            spec=spec,
            location=scan_dir.as_posix(),
            scanners=scanners,
        )


def _read_scan_spec(scan_dir: UPath) -> ScanSpec:
    scan_json = scan_dir / SCAN_JSON
    fs = filesystem(scan_dir.as_posix())
    if not fs.exists(scan_json.as_posix()):
        raise RuntimeError(
            f"The specified directory '{scan_dir}' does not contain a scan."
        )

    with file(scan_json.as_posix(), "r") as f:
        return ScanSpec.model_validate_json(f.read())


def _find_scan_dir(scans_path: UPath, scan_id: str) -> UPath | None:
    _ensure_scans_dir(scans_path)
    for f in scans_path.glob(f"*_{scan_id}"):
        if f.is_dir():
            return f

    return None


def _ensure_scan_dir(scans_path: UPath, scan_id: str, scan_name: str) -> UPath:
    # look for an existing scan dir
    scan_dir = _find_scan_dir(scans_path, scan_id)

    # if there is no scan_dir then create one
    if scan_dir is None:
        scan_dir = (
            scans_path
            / f"{clean_filename_component(iso_now())}_{clean_filename_component(scan_name)}_{scan_id}"
        )
        scan_dir.mkdir(parents=True, exist_ok=False)

    # return scan dir
    return scan_dir


def _ensure_scans_dir(scans_dir: UPath) -> None:
    scans_dir.mkdir(parents=True, exist_ok=True)
    with file((scans_dir / ".gitignore").as_posix(), "w") as f:
        f.write(".*.parquet\n")
