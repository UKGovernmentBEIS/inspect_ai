import json
import zipfile
from dataclasses import dataclass
from typing import Any, Literal
from zipfile import ZipFile

from pydantic import BaseModel, Field
from pydantic_core import to_json
from typing_extensions import override

from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai._util.error import EvalError
from inspect_ai._util.file import file

from .._log import (
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSpec,
    EvalStats,
    sort_samples,
)
from .file import FileRecorder


@dataclass
class ZipLogFile:
    file: str
    zip: ZipFile


class LogStart(BaseModel):
    version: int
    eval: EvalSpec
    plan: EvalPlan


class LogResults(BaseModel):
    status: Literal["started", "success", "cancelled", "error"]
    stats: EvalStats
    results: EvalResults | None = Field(default=None)
    error: EvalError | None = Field(default=None)


START_JSON = "start.json"
RESULTS_JSON = "results.json"
SAMPLES_DIR = "samples"

ZIP_COMPRESSION = zipfile.ZIP_DEFLATED
ZIP_COMPRESSLEVEL = 5


class EvalRecorder(FileRecorder):
    @override
    @classmethod
    def handles_location(cls, location: str) -> bool:
        return location.endswith(".eval")

    def __init__(self, log_dir: str, fs_options: dict[str, Any] = {}):
        super().__init__(log_dir, ".eval", fs_options)

        # each eval has a unique key (created from run_id and task name/version)
        # which we use to track the output path, accumulated data, and event counter
        self.data: dict[str, ZipLogFile] = {}

    @override
    def log_init(self, eval: EvalSpec) -> str:
        log = self._log_file_path(eval)

        self.data[self._log_file_key(eval)] = ZipLogFile(
            file=log,
            zip=ZipFile(
                log,
                mode="a",
                compression=ZIP_COMPRESSION,
                compresslevel=ZIP_COMPRESSLEVEL,
            ),
        )
        return log

    @override
    def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None:
        start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval, plan=plan)
        self._write(eval, START_JSON, start.model_dump())

    @override
    def log_sample(self, eval: EvalSpec, sample: EvalSample) -> None:
        self._write(eval, sample_filename(sample), sample.model_dump())

    @override
    def flush(self, eval: EvalSpec) -> None:
        log = self.data[self._log_file_key(eval)]  # noqa: F841
        # TODO: flush the zip file
        pass

    @override
    def log_finish(
        self,
        eval: EvalSpec,
        status: Literal["success", "cancelled", "error"],
        stats: EvalStats,
        results: EvalResults | None,
        error: EvalError | None = None,
    ) -> EvalLog:
        # ensure all data is written
        self.flush(eval)

        # get the key and log
        key = self._log_file_key(eval)
        log = self.data[key]

        # write the results
        log_results = LogResults(
            status=status, stats=stats, results=results, error=error
        )
        self._write(eval, RESULTS_JSON, log_results.model_dump())

        # close the file
        log.zip.close()

        # stop tracking this eval
        del self.data[key]

        # return the full EvalLog
        return self.read_log(log.file)

    @classmethod
    @override
    def read_log(cls, location: str, header_only: bool = False) -> EvalLog:
        with file(location, "rb") as z:
            zip = ZipFile(z, mode="r")
            with zip.open(START_JSON, "r") as f:
                start = LogStart(**json.load(f))
            with zip.open(RESULTS_JSON, "r") as f:
                results = LogResults(**json.load(f))
            samples: list[EvalSample] | None = None
            if not header_only:
                samples = []
                for name in zip.namelist():
                    if name.startswith(f"{SAMPLES_DIR}/") and name.endswith(".json"):
                        with zip.open(name, "r") as f:
                            samples.append(EvalSample(**json.load(f)))
                sort_samples(samples)

            return EvalLog(
                version=start.version,
                status=results.status,
                eval=start.eval,
                plan=start.plan,
                results=results.results,
                stats=results.stats,
                error=results.error,
                samples=samples,
            )

    @classmethod
    @override
    def write_log(cls, location: str, log: EvalLog) -> None:
        with file(location, "wb") as z:
            zip = ZipFile(z, mode="a", compression=ZIP_COMPRESSION)
            start = LogStart(version=log.version, eval=log.eval, plan=log.plan)
            zip_write(zip, START_JSON, start.model_dump())

            if log.samples:
                for sample in log.samples:
                    zip_write(zip, sample_filename(sample), sample.model_dump())

            results = LogResults(
                status=log.status, stats=log.stats, results=log.results, error=log.error
            )
            zip_write(zip, RESULTS_JSON, results.model_dump())

    # write to the zip file
    def _write(self, eval: EvalSpec, filename: str, data: dict[str, Any]) -> None:
        log = self.data[self._log_file_key(eval)]
        zip_write(log.zip, filename, data)


def zip_write(zip: ZipFile, filename: str, data: dict[str, Any]) -> None:
    zip.writestr(
        filename,
        to_json(value=data, indent=2, exclude_none=True, fallback=lambda _x: None),
    )


def sample_filename(sample: EvalSample) -> str:
    return f"{SAMPLES_DIR}/{sample.id}_epoch_{sample.epoch}.json"
