import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Literal
from zipfile import ZipFile

import fsspec
from pydantic import BaseModel, Field
from pydantic_core import to_json
from typing_extensions import override

from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai._util.error import EvalError
from inspect_ai._util.file import file, open_file
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


@dataclass
class ZipLogFile:
    file: str
    of: fsspec.core.OpenFile
    zip: ZipFile
    samples: list[EvalSample] = field(default_factory=list)
    summaries: list[SampleSummary] = field(default_factory=list)
    summary_counter: int = field(default=0)


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
        # file to write to
        file = self._log_file_path(eval)

        # now open w/ a stream
        of = open_file(file, "wb")
        zip = ZipFile(
            of.open(),
            mode="a",
            compression=ZIP_COMPRESSION,
            compresslevel=ZIP_COMPRESSLEVEL,
        )

        # Initialize the summary counter and existing summaries
        summary_counter = _read_summary_counter(zip)
        summaries = _read_all_summaries(zip, summary_counter)

        self.data[self._log_file_key(eval)] = ZipLogFile(
            file=file,
            of=of,
            zip=zip,
            summary_counter=summary_counter,
            summaries=summaries,
        )

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
        log = self.data[self._log_file_key(eval)]  # noqa: F841
        # TODO: flush the zip file

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
        log.zip.close()
        log.of.close()

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
    def _write(
        self, eval: EvalSpec, filename: str, data: dict[str, Any] | list[Any]
    ) -> None:
        log = self.data[self._log_file_key(eval)]
        zip_write(log.zip, filename, data)


def zip_write(zip: ZipFile, filename: str, data: dict[str, Any] | list[Any]) -> None:
    zip.writestr(
        filename,
        to_json(value=data, indent=2, exclude_none=True, fallback=lambda _x: None),
    )


def sample_filename(sample: EvalSample) -> str:
    return f"{SAMPLES_DIR}/{sample.id}_epoch_{sample.epoch}.json"


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
