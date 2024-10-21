import json
import tempfile
from typing import Any, BinaryIO, Literal, cast
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, Field
from pydantic_core import to_json
from typing_extensions import override

from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai._util.error import EvalError
from inspect_ai._util.file import dirname, file
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.scorer._metric import Score

from .._log import (
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
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


JOURNAL_DIR = "_journal"
SUMMARY_DIR = "summaries"
SAMPLES_DIR = "samples"

START_JSON = "start.json"
RESULTS_JSON = "results.json"
REDUCTIONS_JSON = "reductions.json"
SUMMARIES_JSON = "summaries.json"
HEADER_JSON = "header.json"


class EvalRecorder(FileRecorder):
    @override
    @classmethod
    def handles_location(cls, location: str) -> bool:
        return location.endswith(".eval")

    @override
    def default_log_buffer(self) -> int:
        # .eval files are 5-8x smaller than .json files so we
        # are much less worried about flushing frequently
        return 10

    def __init__(self, log_dir: str, fs_options: dict[str, Any] = {}):
        super().__init__(log_dir, ".eval", fs_options)

        # each eval has a unique key (created from run_id and task name/version)
        # which we use to track the output path, accumulated data, and event counter
        self.data: dict[str, ZipLogFile] = {}

    @override
    def log_init(self, eval: EvalSpec, location: str | None = None) -> str:
        # file to write to
        file = location or self._log_file_path(eval)

        # create zip wrapper
        zip_log_file = ZipLogFile(file=file)

        # Initialize the summary counter and existing summaries
        summary_counter = _read_summary_counter(zip_log_file.zip)
        summaries = _read_all_summaries(zip_log_file.zip, summary_counter)

        # Initialize the eval header (without results)
        log_start = _read_start(zip_log_file.zip)

        # The zip log file
        zip_log_file.init(log_start, summary_counter, summaries)

        # track zip
        self.data[self._log_file_key(eval)] = zip_log_file

        # return file path
        return file

    @override
    def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None:
        start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval, plan=plan)
        self._write(eval, _journal_path(START_JSON), start)

        log = self.data[self._log_file_key(eval)]  # noqa: F841
        log.log_start = start

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
        status: Literal["started", "success", "cancelled", "error"],
        stats: EvalStats,
        results: EvalResults | None,
        reductions: list[EvalSampleReductions] | None,
        error: EvalError | None = None,
    ) -> EvalLog:
        # get the key and log
        key = self._log_file_key(eval)
        log = self.data[key]

        # write the buffered samples
        self._write_buffered_samples(eval)

        # write consolidated summaries
        self._write(eval, SUMMARIES_JSON, log.summaries)

        # write reductions
        if reductions is not None:
            self._write(
                eval,
                REDUCTIONS_JSON,
                reductions,
            )

        # Get the results
        log_results = LogResults(
            status=status, stats=stats, results=results, error=error
        )

        # add the results to the original eval log from start.json
        log_start = log.log_start
        if log_start is None:
            raise RuntimeError("Unexpectedly issing the log start value")

        eval_header = EvalLog(
            version=log_start.version,
            eval=log_start.eval,
            plan=log_start.plan,
            results=log_results.results,
            stats=log_results.stats,
            status=log_results.status,
            error=log_results.error,
        )

        # write the results
        self._write(eval, HEADER_JSON, eval_header)

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
            with ZipFile(z, mode="r") as zip:
                evalLog = _read_header(zip)
                if REDUCTIONS_JSON in zip.namelist():
                    with zip.open(REDUCTIONS_JSON, "r") as f:
                        reductions = [
                            EvalSampleReductions(**reduction)
                            for reduction in json.load(f)
                        ]
                        if evalLog.results is not None:
                            evalLog.reductions = reductions

                samples: list[EvalSample] | None = None
                if not header_only:
                    samples = []
                    for name in zip.namelist():
                        if name.startswith(f"{SAMPLES_DIR}/") and name.endswith(
                            ".json"
                        ):
                            with zip.open(name, "r") as f:
                                samples.append(EvalSample(**json.load(f)))
                    sort_samples(samples)
                    evalLog.samples = samples
                return evalLog

    @override
    @classmethod
    def read_log_sample(
        cls, location: str, id: str | int, epoch: int = 1
    ) -> EvalSample:
        with file(location, "rb") as z:
            with ZipFile(z, mode="r") as zip:
                with zip.open(_sample_filename(id, epoch), "r") as f:
                    return EvalSample(**json.load(f))

    @classmethod
    @override
    def write_log(cls, location: str, log: EvalLog) -> None:
        # write using the recorder (so we get all of the extra streams)
        recorder = EvalRecorder(dirname(location))
        recorder.log_init(log.eval, location)
        recorder.log_start(log.eval, log.plan)
        for sample in log.samples or []:
            recorder.log_sample(log.eval, sample)
        recorder.log_finish(
            log.eval, log.status, log.stats, log.results, log.reductions, log.error
        )

    # write to the zip file
    def _write(self, eval: EvalSpec, filename: str, data: Any) -> None:
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
            self._write(eval, _sample_filename(sample.id, sample.epoch), sample)

            # Capture the summary
            summaries.append(
                SampleSummary(
                    id=sample.id,
                    epoch=sample.epoch,
                    input=text_inputs(sample.input),
                    target=sample.target,
                    scores=sample.scores,
                )
            )
        log.samples.clear()

        # write intermediary summaries and add to master list
        if len(summaries) > 0:
            log.summary_counter += 1
            summary_file = _journal_summary_file(log.summary_counter)
            summary_path = _journal_summary_path(summary_file)
            self._write(eval, summary_path, summaries)
            log.summaries.extend(summaries)


def zip_write(zip: ZipFile, filename: str, data: Any) -> None:
    zip.writestr(
        filename,
        to_json(value=data, indent=2, exclude_none=True, fallback=lambda _x: None),
    )


def text_inputs(inputs: str | list[ChatMessage]) -> str | list[ChatMessage]:
    # Clean the input of any images
    if isinstance(inputs, list):
        input: list[ChatMessage] = []
        for message in inputs:
            if not isinstance(message.content, str):
                filtered_content: list[ContentText | ContentImage] = []
                for content in message.content:
                    if content.type != "image":
                        filtered_content.append(content)
                if len(filtered_content) == 0:
                    filtered_content.append(ContentText(text="(Image)"))
                message.content = filtered_content
                input.append(message)

        return input
    else:
        return inputs


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
        self.log_start: LogStart | None = None

    def init(
        self,
        log_start: LogStart | None,
        summary_counter: int,
        summaries: list[SampleSummary],
    ) -> None:
        self.summary_counter = summary_counter
        self.summaries = summaries
        self.log_start = log_start

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


def _read_start(zip: ZipFile) -> LogStart | None:
    start_path = _journal_path(START_JSON)
    if start_path in zip.namelist():
        return cast(LogStart, _read_json(zip, start_path))
    else:
        return None


def _read_summary_counter(zip: ZipFile) -> int:
    current_count = 0
    for name in zip.namelist():
        if name.startswith(_journal_summary_path()) and name.endswith(".json"):
            this_count = int(name.split("/")[-1].split(".")[0])
            current_count = max(this_count, current_count)
    return current_count


def _read_all_summaries(zip: ZipFile, count: int) -> list[SampleSummary]:
    if SUMMARIES_JSON in zip.namelist():
        summaries_raw = _read_json(zip, SUMMARIES_JSON)
        if isinstance(summaries_raw, list):
            return [SampleSummary(**value) for value in summaries_raw]
        else:
            raise ValueError(
                f"Expected a list of summaries when reading {SUMMARIES_JSON}"
            )
    else:
        summaries: list[SampleSummary] = []
        for i in range(1, count):
            summary_file = _journal_summary_file(i)
            summary_path = _journal_summary_path(summary_file)
            summary = _read_json(zip, summary_path)
            if isinstance(summary, list):
                summaries.extend([SampleSummary(**value) for value in summary])
            else:
                raise ValueError(
                    f"Expected a list of summaries when reading {summary_file}"
                )
        return summaries


def _read_header(zip: ZipFile) -> EvalLog:
    # first see if the header is here
    if HEADER_JSON in zip.namelist():
        with zip.open(HEADER_JSON, "r") as f:
            return EvalLog(**json.load(f))
    else:
        with zip.open(_journal_path(START_JSON), "r") as f:
            start = LogStart(**json.load(f))
        return EvalLog(
            version=start.version,
            eval=start.eval,
            plan=start.plan,
        )


def _sample_filename(id: str | int, epoch: int) -> str:
    return f"{SAMPLES_DIR}/{id}_epoch_{epoch}.json"


def _read_json(zip: ZipFile, filename: str) -> Any:
    with zip.open(filename) as f:
        return json.load(f)


def _journal_path(file: str) -> str:
    return JOURNAL_DIR + "/" + file


def _journal_summary_path(file: str | None = None) -> str:
    if file is None:
        return _journal_path(SUMMARY_DIR)
    else:
        return f"{_journal_path(SUMMARY_DIR)}/{file}"


def _journal_summary_file(index: int) -> str:
    return f"{index}.json"
