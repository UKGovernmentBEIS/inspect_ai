from typing import Any, AsyncIterable, BinaryIO, Literal, get_args

import ijson  # type: ignore
from fsspec.asyn import AbstractAsyncStreamedFile, AsyncFileSystem  # type: ignore
from ijson import IncompleteJSONError
from pydantic import BaseModel
from pydantic_core import from_json
from typing_extensions import override

from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai._util.error import EvalError
from inspect_ai._util.file import (
    absolute_file_path,
    async_fileystem,
    file,
    filesystem,
)

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


class JSONRecorder(FileRecorder):
    @override
    @classmethod
    def handles_location(cls, location: str) -> bool:
        return location.endswith(".json")

    @override
    def default_log_buffer(self) -> int:
        # we write the entire file in one shot and the files can
        # get fairly large (> 100MB) so we are a bit more sparing
        # for remote filesystem writes
        if self.is_local():
            return 10
        else:
            return 100

    class JSONLogFile(BaseModel):
        file: str
        data: EvalLog

    def __init__(
        self, log_dir: str, suffix: str = ".json", fs_options: dict[str, Any] = {}
    ):
        # call super
        super().__init__(log_dir, suffix, fs_options)

        # each eval has a unique key (created from run_id and task name/version)
        # which we use to track the output path, accumulated data, and event counter
        self.data: dict[str, JSONRecorder.JSONLogFile] = {}

    @override
    async def log_init(self, eval: EvalSpec, location: str | None = None) -> str:
        # initialize file log for this eval
        # compute an absolute path if it's a relative ref
        # (so that the writes go to the correct place even
        # if the working directory is switched for a task)
        file = location or absolute_file_path(self._log_file_path(eval))

        # compute an absolute path if it's a relative ref
        # (so that the writes go to the correct place even
        # if the working directory is switched for a task)
        self.data[self._log_file_key(eval)] = JSONRecorder.JSONLogFile(
            file=file, data=EvalLog(eval=eval)
        )

        # attempt to
        return file

    @override
    async def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None:
        log = self.data[self._log_file_key(eval)]
        log.data.plan = plan

    @override
    async def log_sample(self, eval: EvalSpec, sample: EvalSample) -> None:
        log = self.data[self._log_file_key(eval)]
        if log.data.samples is None:
            log.data.samples = []
        log.data.samples.append(sample)

    @override
    async def log_finish(
        self,
        spec: EvalSpec,
        status: Literal["started", "success", "cancelled", "error"],
        stats: EvalStats,
        results: EvalResults | None,
        error: EvalError | None = None,
    ) -> EvalLog:
        log = self.data[self._log_file_key(spec)]
        log.data.status = status
        log.data.stats = stats
        log.data.results = results
        if error:
            log.data.error = error
        await self.write_log(log.file, log.data)

        # stop tracking this data
        del self.data[self._log_file_key(spec)]

        # return the log
        return log.data

    @override
    async def flush(self, eval: EvalSpec) -> None:
        log = self.data[self._log_file_key(eval)]
        await self.write_log(log.file, log.data)

    @override
    @classmethod
    async def read_log(cls, location: str, header_only: bool = False) -> EvalLog:
        # get s3 fileystem if appropriate
        s3_fs = async_fileystem(location) if filesystem(location).is_s3() else None

        if header_only:
            try:
                return await _read_header(location, s3_fs)
            # The Python JSON serializer supports NaN and Inf, however
            # this isn't technically part of the JSON spec. The json-stream
            # library shares this limitation, so if we fail with an
            # invalid character then we move on and and parse w/ pydantic
            # (which does support NaN and Inf by default)
            except (ValueError, IncompleteJSONError) as ex:
                if (
                    str(ex).find("Invalid JSON character") != -1
                    or str(ex).find("invalid char in json text") != -1
                ):
                    pass
                else:
                    raise ValueError(f"Unable to read log file: {location}") from ex

        # parse full log (also used as a fallback for header_only encountering NaN or Inf)

        # read async for s3
        if s3_fs:
            af = await s3_fs.open_async(location)
            try:
                bytes = await af.read()
            finally:
                await af.close()
        else:
            with file(location, "rb") as f:
                bytes = f.read()

        # parse json
        raw_data = from_json(bytes)
        log = EvalLog(**raw_data)

        # fail for unknown version
        _validate_version(log.version)

        # set the version to the schema version we'll be returning
        log.version = LOG_SCHEMA_VERSION

        # prune if header_only
        if header_only:
            # exclude samples
            log.samples = None

            # prune sample reductions
            if log.results is not None:
                log.results.sample_reductions = None

        # return log
        return log

    @override
    @classmethod
    async def read_log_sample(
        cls, location: str, id: str | int, epoch: int = 1
    ) -> EvalSample:
        raise NotImplementedError(
            "read_log_sample is not supported for .json log files."
        )

    @override
    @classmethod
    async def write_log(cls, location: str, log: EvalLog) -> None:
        from inspect_ai.log._file import eval_log_json

        # sort samples before writing as they can come in out of order
        if log.samples:
            sort_samples(log.samples)

        with file(location, "w") as f:
            f.write(eval_log_json(log))


def _validate_version(ver: int) -> None:
    if ver > LOG_SCHEMA_VERSION:
        raise ValueError(f"Unable to read version {ver} of log format.")


class IJsonReader:
    def __init__(self, f: BinaryIO) -> None:
        self.f = f

    async def seek(self, offset: int) -> None:
        self.f.seek(offset)

    async def parse(self) -> AsyncIterable[tuple[str, str, Any]]:
        for prefix, event, value in ijson.parse(self.f):
            yield prefix, event, value

    async def kvitems(self) -> AsyncIterable[tuple[str, Any]]:
        for k, v in ijson.kvitems(self.f, ""):
            yield k, v


class IJsonAsyncReader(IJsonReader):
    def __init__(self, f: AbstractAsyncStreamedFile) -> None:
        self.af = f

    async def seek(self, offset: int) -> None:
        self.af.seek(offset)

    async def parse(self) -> AsyncIterable[tuple[str, str, Any]]:
        async for prefix, event, value in ijson.parse_async(self.af):
            yield prefix, event, value

    async def kvitems(self) -> AsyncIterable[tuple[str, Any]]:
        async for k, v in ijson.kvitems_async(self.af, ""):
            yield k, v


async def _read_header(log_file: str, s3_fs: AsyncFileSystem | None) -> EvalLog:
    # read version and status
    if s3_fs:
        af = await s3_fs.open_async(log_file)
        json_stream = IJsonAsyncReader(af)
        try:
            version, has_results, has_error = await _read_version_and_status(
                json_stream
            )
        finally:
            await af.close()
    else:
        with file(log_file, "rb") as f:
            version, has_results, has_error = await _read_version_and_status(
                IJsonReader(f)
            )

    # read the rest of the log
    if s3_fs:
        af = await s3_fs.open_async(log_file)
        json_stream = IJsonAsyncReader(af)
        try:
            return await _read_log(json_stream, version, has_results, has_error)
        finally:
            await af.close()
    else:
        with file(log_file, "rb") as f:
            return await _read_log(IJsonReader(f), version, has_results, has_error)


async def _read_version_and_status(
    json_stream: IJsonReader,
) -> tuple[int, bool, bool]:
    # Do low-level parsing to get the version number and also
    # detect the presence of results or error sections
    version: int | None = None
    has_results = False
    has_error = False

    async for prefix, event, value in json_stream.parse():
        if (prefix, event) == ("version", "number"):
            version = value
        elif (prefix, event) == ("results", "start_map"):
            has_results = True
        elif (prefix, event) == ("error", "start_map"):
            has_error = True
        elif prefix == "samples":
            # Break as soon as we hit samples as that can be very large
            break

    if version is None:
        raise ValueError("Unable to read version of log format.")

    _validate_version(version)
    version = LOG_SCHEMA_VERSION

    return version, has_results, has_error


async def _read_log(
    json_stream: IJsonReader, version: int, has_results: bool, has_error: bool
) -> EvalLog:
    # Parse the log file, stopping before parsing samples
    async for k, v in json_stream.kvitems():
        if k == "status":
            assert v in get_args(Literal["started", "success", "cancelled", "error"])
            status: Literal["started", "success", "cancelled", "error"] = v
        if k == "eval":
            eval = EvalSpec(**v)
        elif k == "plan":
            plan = EvalPlan(**v)
        elif k == "results":
            results = EvalResults(**v)
        elif k == "stats":
            stats = EvalStats(**v)
            if not has_error:
                # Exit before parsing samples
                break
        elif k == "error":
            error = EvalError(**v)
            break

    return EvalLog(
        eval=eval,
        plan=plan,
        results=results if has_results else None,
        stats=stats,
        status=status,
        version=version,
        error=error if has_error else None,
    )
