from typing import Sequence, override

from upath import UPath

from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.file import clean_filename_component, file, filesystem
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.scanner._recorder.buffer import RecorderBuffer
from inspect_ai.scanner._scanner.result import Result
from inspect_ai.scanner._scanspec import ScanSpec
from inspect_ai.scanner._transcript.types import TranscriptInfo

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
            UPath(scans_location), spec.job_id, spec.job_name or "job"
        )
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
        self._scan_spec = _read_scan_spec(self._scan_dir)
        self._scan_buffer = RecorderBuffer(self._scan_dir.as_posix())
        return self._scan_spec

    @override
    async def is_recorded(self, transcript: TranscriptInfo, scanner: str) -> bool:
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
    async def complete(self) -> ScanResults:
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq

        # get scanners
        scanners: dict[str, pa.Table] = {}
        for scanner in sorted(self.scan_spec.scanners.keys()):
            tbl = await self._scan_buffer.table_for_scanner(scanner)
            if tbl is not None:
                scanners[scanner] = tbl

        for name, table in scanners.items():
            # write directly with Arrow
            pq.write_table(
                table,
                (self.scan_dir / f"{name}.parquet").as_posix(),
                compression="zstd",
                use_dictionary=True,
            )

        # return results
        scanners_pd = {
            n: t.to_pandas(types_mapper=pd.ArrowDtype) for n, t in scanners.items()
        }
        return ScanResults(
            spec=self.scan_spec,
            location=self.scan_dir.as_posix(),
            scanners=scanners_pd,
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
        import pyarrow.parquet as pq
        from upath import UPath

        scan_dir = UPath(scan_location)
        spec = _read_scan_spec(scan_dir)

        scanners: dict[str, pd.DataFrame] = {}
        for parquet_file in sorted(scan_dir.glob("*.parquet")):
            # Read with Arrow, then convert using Arrow-backed pandas dtypes
            name = parquet_file.stem
            table = pq.read_table(parquet_file.as_posix(), memory_map=True)
            df = table.to_pandas(types_mapper=pd.ArrowDtype)
            scanners[name] = df

        return ScanResults(spec=spec, location=scan_dir.as_posix(), scanners=scanners)


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
