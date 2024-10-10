import json
import tempfile
import zipfile
from typing import Any, BinaryIO, Literal, cast

from pydantic import BaseModel, Field
from pydantic_core import to_json
from typing_extensions import override
from zipfile_deflate64 import ZIP_DEFLATED, ZipFile  # type: ignore

from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai._util.error import EvalError
from inspect_ai._util.file import file
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.scorer._metric import Score

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


class SampleSummary(BaseModel):
    id: int | str
    epoch: int
    input: str | list[ChatMessage]
    target: str | list[str]
    scores: dict[str, Score] | None


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
SUMMARY_JSON = "summary.json"
REDUCTIONS_JSON = "reductions.json"
SAMPLES_DIR = "samples"


class EvalRecorder(FileRecorder):
    @override
    @classmethod
    def handles_location(cls, location: str) -> bool:
        return location.endswith(".eval")

    @override
    def default_log_buffer(self) -> int:
        # .eval files are 5-8x smaller than .json files so we
        # are much less worried about flushing frequently
        if self.is_local():
            return 5
        else:
            return 10

    def __init__(self, log_dir: str, fs_options: dict[str, Any] = {}):
        super().__init__(log_dir, ".eval", fs_options)

        # each eval has a unique key (created from run_id and task name/version)
        # which we use to track the output path, accumulated data, and event counter
        self.data: dict[str, ZipLogFile] = {}

    @override
    def log_init(self, eval: EvalSpec) -> str:
        # file to write to
        file = self._log_file_path(eval)

        # create zip wrapper
        zip_log_file = ZipLogFile(file=file)

        # Initialize the summary counter and existing summaries
        summary_counter = _read_summary_counter(zip_log_file.zip)
        summaries = _read_all_summaries(zip_log_file.zip, summary_counter)
        zip_log_file.init(summary_counter, summaries)

        # track zip
        self.data[self._log_file_key(eval)] = zip_log_file

        # return file path
        return file

    @override
    def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None:
        start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval, plan=plan)
        self._write(eval, START_JSON, start.model_dump())

    @override
    def log_sample(self, eval: EvalSpec, sample: EvalSample) -> None:
        log = self.data[self._log_file_key(eval)]  # noqa: F841
        log.samples.append(sample)

    @override
    def flush(self, eval: EvalSpec) -> None:
        # get the zip log
        log = self.data[self._log_file_key(eval)]

        # write the buffered samples
        self._write_buffered_samples(eval)

        # flush to underlying stream
        log.flush()

    @override
    def log_finish(
        self,
        eval: EvalSpec,
        status: Literal["success", "cancelled", "error"],
        stats: EvalStats,
        results: EvalResults | None,
        error: EvalError | None = None,
    ) -> EvalLog:
        # get the key and log
        key = self._log_file_key(eval)
        log = self.data[key]

        # write the buffered samples
        self._write_buffered_samples(eval)

        # write consolidated summaries
        self._write(eval, SUMMARY_JSON, [item.model_dump() for item in log.summaries])

        # write reductions
        if results is not None:
            reductions = results.sample_reductions
            if reductions is not None:
                self._write(
                    eval,
                    REDUCTIONS_JSON,
                    [reduction.model_dump() for reduction in reductions],
                )

                # prune reductions out of the results to ensure
                #  that the results remain concise
                results = EvalResults(
                    total_samples=results.total_samples,
                    completed_samples=results.completed_samples,
                    scores=results.scores,
                    metadata=results.metadata,
                )

        # write the results
        log_results = LogResults(
            status=status, stats=stats, results=results, error=error
        )
        self._write(eval, RESULTS_JSON, log_results.model_dump())

        # close the file
        log.close()

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
            zip = ZipFile(z, mode="a", compression=zipfile.ZIP_DEFLATED)
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
    def _write(
        self, eval: EvalSpec, filename: str, data: dict[str, Any] | list[Any]
    ) -> None:
        log = self.data[self._log_file_key(eval)]
        zip_write(log.zip, filename, data)

    # write buffered samples to the zip file
    def _write_buffered_samples(self, eval: EvalSpec) -> None:
        # get the log
        log = self.data[self._log_file_key(eval)]

        # Write the buffered samples
        summaries: list[SampleSummary] = []
        for sample in log.samples:
            # Write the sample
            self._write(eval, sample_filename(sample), sample.model_dump())

            # Capture the summary
            summaries.append(
                SampleSummary(
                    id=sample.id,
                    epoch=sample.epoch,
                    input=sample.input,
                    target=sample.target,
                    scores=sample.scores,
                )
            )
        log.samples.clear()

        # write intermediary summaries and add to master list
        if len(summaries) > 0:
            log.summary_counter += 1
            summary_filename = f"summaries/{log.summary_counter}.json"
            self._write(eval, summary_filename, summaries)
            log.summaries.extend(summaries)


def zip_write(zip: ZipFile, filename: str, data: dict[str, Any] | list[Any]) -> None:
    zip.writestr(
        filename,
        to_json(value=data, indent=2, exclude_none=True, fallback=lambda _x: None),
    )


def sample_filename(sample: EvalSample) -> str:
    return f"{SAMPLES_DIR}/{sample.id}_epoch_{sample.epoch}.json"


class ZipLogFile:
    TEMP_LOG_FILE_MAX = 20 * 1024 * 1024

    zip: ZipFile
    temp_file: BinaryIO

    def __init__(self, file: str) -> None:
        self.file = file
        self.temp_file = cast(
            BinaryIO,
            tempfile.SpooledTemporaryFile(self.TEMP_LOG_FILE_MAX),
        )
        self._open()
        self.samples: list[EvalSample] = []
        self.summary_counter = 0
        self.summaries: list[SampleSummary] = []

    def init(self, summary_counter: int, summaries: list[SampleSummary]) -> None:
        self.summary_counter = summary_counter
        self.summaries = summaries

    def flush(self) -> None:
        self.zip.close()
        self.temp_file.seek(0)
        with file(self.file, "wb") as f:
            f.write(self.temp_file.read())
        self._open()

    def close(self) -> None:
        self.flush()
        self.temp_file.close()

    def _open(self) -> None:
        self.zip = ZipFile(
            self.temp_file,
            mode="a",
            compression=ZIP_DEFLATED,
            compresslevel=5,
        )


def _read_summary_counter(zip: ZipFile) -> int:
    current_count = 0
    for name in zip.namelist():
        if name.startswith("summaries/") and name.endswith(".json"):
            this_count = int(name.split("/")[-1].split(".")[0])
            current_count = max(this_count, current_count)
    return current_count


def _read_all_summaries(zip: ZipFile, count: int) -> list[SampleSummary]:
    if "summary.json" in zip.namelist():
        summaries_raw = _read_json(zip, SUMMARY_JSON)
        if isinstance(summaries_raw, list):
            return [SampleSummary(**value) for value in summaries_raw]
        else:
            raise ValueError("Expected a list of summaries when reading summary.json")
    else:
        summaries: list[SampleSummary] = []
        for i in range(1, count):
            summary_file = f"summaries/{i}.json"
            summary = _read_json(zip, summary_file)
            if isinstance(summary, list):
                summaries.extend([SampleSummary(**value) for value in summary])
            else:
                raise ValueError(
                    f"Expected a list of summaries when reading {summary_file}"
                )
        return summaries


def _read_json(zip: ZipFile, filename: str) -> Any:
    with zip.open(filename) as f:
        return json.load(f)
