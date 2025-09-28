from typing import Sequence, override

from upath import UPath

from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.file import clean_filename_component, file, filesystem
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.scanner._recorder.buffer import RecorderBuffer
from inspect_ai.scanner._scanner.result import Result
from inspect_ai.scanner._scanspec import ScanSpec
from inspect_ai.scanner._transcript.types import TranscriptInfo

from .recorder import ScanRecorder, ScanResults, ScanStatus

SCAN_JSON = "_scan.json"


class FileRecorder(ScanRecorder):
    def __init__(self) -> None:
        self._scan_dir: UPath | None = None
        self._scan_spec: ScanSpec | None = None

    @override
    async def init(self, spec: ScanSpec, scans_location: str) -> None:
        # create the scan dir
        self._scan_dir = _ensure_scan_dir(
            UPath(scans_location), spec.job_id, spec.job_name or "job"
        )
        self._scan_fs = filesystem(self._scan_dir.as_posix())
        # write the spec
        with file((self.scan_dir / SCAN_JSON).as_posix(), "w") as f:
            f.write(to_json_str_safe(spec))
        # save the spec
        self._scan_spec = spec

        # create the scan buffer
        self._scan_buffer = RecorderBuffer(self._scan_dir.as_posix())

    @override
    async def resume(self, scan_location: str) -> ScanSpec:
        self._scan_dir = UPath(scan_location)
        self._scan_fs = filesystem(self._scan_dir.as_posix())
        self._scan_spec = _read_scan_spec(self._scan_dir)
        self._scan_buffer = RecorderBuffer(self._scan_dir.as_posix())
        return self._scan_spec

    @override
    async def location(self) -> str:
        return self.scan_dir.as_posix()

    @override
    async def is_recorded(self, transcript: TranscriptInfo, scanner: str) -> bool:
        # if we either already have a final scanner file or this transcript
        # is in the buffer then the scan is recorded
        if self._scan_fs.exists(self._scanner_parquet_file(scanner)):
            return True
        else:
            return await self._scan_buffer.is_recorded(transcript, scanner)

    @override
    async def record(
        self, transcript: TranscriptInfo, scanner: str, results: Sequence[Result]
    ) -> None:
        await self._scan_buffer.record(transcript, scanner, results)

    @override
    async def flush(self) -> None:
        pass

    @override
    async def complete(self) -> ScanStatus:
        # write scanners
        for scanner in sorted(self.scan_spec.scanners.keys()):
            await self._scan_buffer.write_table_for_scanner(
                scanner, self._scanner_parquet_file(scanner)
            )

        # cleanup scan buffer
        self._scan_buffer.cleanup()

        return ScanStatus(
            complete=True,
            spec=self.scan_spec,
            location=self.scan_dir.as_posix(),
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
    async def status(scan_location: str) -> ScanStatus:
        buffer_dir = RecorderBuffer.buffer_dir(scan_location)
        return ScanStatus(
            complete=False if buffer_dir.exists() else True,
            spec=_read_scan_spec(UPath(scan_location)),
            location=scan_location,
        )

    @staticmethod
    async def results(scan_location: str, scanner: str | None = None) -> ScanResults:
        import pandas as pd
        import pyarrow.parquet as pq
        from upath import UPath

        scan_dir = UPath(scan_location)
        status = await FileRecorder.status(scan_location)

        def scanner_df(parquet_file: UPath) -> pd.DataFrame:
            # Read with Arrow, then convert using Arrow-backed pandas dtypes
            table = pq.read_table(parquet_file.as_posix())
            return table.to_pandas(types_mapper=pd.ArrowDtype)

        # read scanner parquet files
        scanners: dict[str, pd.DataFrame] = {}

        # single scanner
        if scanner is not None:
            parquet_file = scan_dir / f"{scanner}.parquet"
            scanners[scanner] = scanner_df(parquet_file)

        # all scanners
        else:
            for parquet_file in sorted(scan_dir.glob("*.parquet")):
                name = parquet_file.stem
                scanners[name] = scanner_df(parquet_file)

        return ScanResults(
            status=status.complete,
            spec=status.spec,
            location=status.location,
            scanners=scanners,
        )

    def _scanner_parquet_file(self, scanner: str) -> str:
        return (self.scan_dir / f"{scanner}.parquet").as_posix()


def _read_scan_spec(scan_dir: UPath) -> ScanSpec:
    scan_json = scan_dir / SCAN_JSON
    fs = filesystem(scan_dir.as_posix())
    if not fs.exists(scan_json.as_posix()):
        raise RuntimeError(
            f"The specified directory '{scan_dir}' does not contain a scan."
        )

    with file(scan_json.as_posix(), "r") as f:
        return ScanSpec.model_validate_json(f.read())


def _find_scan_dir(scans_path: UPath, job_id: str) -> UPath | None:
    _ensure_scans_dir(scans_path)
    for f in scans_path.glob(f"*_{job_id}"):
        if f.is_dir():
            return f

    return None


def _ensure_scan_dir(scans_path: UPath, job_id: str, job_name: str) -> UPath:
    # look for an existing scan dir
    scan_dir = _find_scan_dir(scans_path, job_id)

    # if there is no scan_dir then create one
    if scan_dir is None:
        scan_dir = (
            scans_path
            / f"{clean_filename_component(iso_now())}_{clean_filename_component(job_name)}_{job_id}"
        )
        scan_dir.mkdir(parents=True, exist_ok=False)

    # return scan dir
    return scan_dir


def _ensure_scans_dir(scans_dir: UPath) -> None:
    scans_dir.mkdir(parents=True, exist_ok=True)
