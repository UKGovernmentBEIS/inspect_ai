import os
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, Field
from typing_extensions import override

from inspect_ai._display.core.display import TaskDisplayMetric
from inspect_ai._util.constants import DEFAULT_LOG_SHARED, EVAL_LOG_FORMAT
from inspect_ai._util.file import FileSystem, basename, dirname, file, filesystem
from inspect_ai._util.json import to_json_safe, to_json_str_safe
from inspect_ai.log._file import read_eval_log

from ..._log import EvalSampleSummary
from .types import SampleBuffer, SampleData, Samples

logger = getLogger(__name__)


class Segment(BaseModel):
    id: int
    last_event_id: int
    last_attachment_id: int


class SegmentFile(BaseModel):
    id: str | int
    epoch: int
    data: SampleData


class SampleManifest(BaseModel):
    summary: EvalSampleSummary
    segments: list[int] = Field(default_factory=list)


class Manifest(BaseModel):
    metrics: list[TaskDisplayMetric] = Field(default_factory=list)
    samples: list[SampleManifest] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)


MANIFEST = "manifest.json"


class SampleBufferFilestore(SampleBuffer):
    def __init__(
        self,
        location: str,
        *,
        create: bool = True,
        update_interval: int = DEFAULT_LOG_SHARED,
    ) -> None:
        self._fs = filesystem(location)
        self._dir = f"{sample_buffer_dir(dirname(location), self._fs)}{self._fs.sep}{os.path.splitext(basename(location))[0]}{self._fs.sep}"
        self.update_interval = update_interval

        if create:
            self._fs.mkdir(self._dir, exist_ok=True)

            # place a file in the dir to force it to be created
            self._fs.touch(f"{self._dir}.keep")

    def write_manifest(self, manifest: Manifest) -> None:
        with file(self._manifest_file(), "wb") as f:
            f.write(to_json_safe(manifest))

    def write_segment(self, id: int, files: list[SegmentFile]) -> None:
        # write the file locally
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as segment_file:
            name = segment_file.name
            with ZipFile(
                segment_file, mode="w", compression=ZIP_DEFLATED, compresslevel=5
            ) as zip:
                for sf in files:
                    zip.writestr(
                        segment_file_name(sf.id, sf.epoch),
                        to_json_str_safe(sf.data),
                    )
            segment_file.flush()
            os.fsync(segment_file.fileno())

        # write then move for atomicity
        try:
            with open(name, "rb") as zf:
                with file(f"{self._dir}{segment_name(id)}", "wb") as f:
                    f.write(zf.read())
                    f.flush()
        finally:
            os.unlink(name)

    def read_manifest(self) -> Manifest | None:
        try:
            with file(self._manifest_file(), "r") as f:
                contents = f.read()
                return Manifest.model_validate_json(contents)
        except FileNotFoundError:
            return None

    def read_segment_data(
        self, id: int, sample_id: str | int, epoch_id: int
    ) -> SampleData:
        segment_file = f"{self._dir}{segment_name(id)}"
        with file(segment_file, "rb") as f:
            with ZipFile(f, mode="r") as zip:
                with zip.open(segment_file_name(sample_id, epoch_id), "r") as sf:
                    return SampleData.model_validate_json(sf.read())

    def cleanup(self) -> None:
        cleanup_sample_buffer_filestore(self._dir, self._fs)

    @classmethod
    @override
    def running_tasks(cls, log_dir: str) -> list[str] | None:
        buffer_dir = Path(sample_buffer_dir(log_dir))
        if buffer_dir.exists():
            return [
                f"{basename(path.name)}.{EVAL_LOG_FORMAT}"
                for path in buffer_dir.iterdir()
                if path.is_dir()
            ]
        else:
            return None

    @override
    def get_samples(
        self, etag: str | None = None
    ) -> Samples | Literal["NotModified"] | None:
        # get the etag on the filestore
        try:
            info = self._fs.info(self._manifest_file())
            fs_etag = info.etag or f"{info.mtime}{info.size}"
        except FileNotFoundError:
            return None

        # if the etag matches then return not modified
        if etag == fs_etag:
            return "NotModified"

        # read the manifest
        manifest = self.read_manifest()
        if manifest is None:
            return None

        # provide samples + etag from the manifest
        return Samples(
            samples=[sm.summary for sm in manifest.samples],
            metrics=manifest.metrics,
            refresh=self.update_interval,
            etag=fs_etag,
        )

    @override
    def get_sample_data(
        self,
        id: str | int,
        epoch: int,
        after_event_id: int | None = None,
        after_attachment_id: int | None = None,
    ) -> SampleData | None:
        # read the manifest
        manifest = self.read_manifest()
        if manifest is None:
            return None

        # find this sample in the manifest
        sample = next(
            (
                sample
                for sample in manifest.samples
                if sample.summary.id == id and sample.summary.epoch == epoch
            ),
            None,
        )
        if sample is None:
            return None

        # determine which segments we need to return in order to
        # satisfy the after_event_id and after_attachment_id
        after_event_id = after_event_id or -1
        after_attachment_id = after_attachment_id or -1
        segments = [
            segment for segment in manifest.segments if segment.id in sample.segments
        ]
        segments = [
            segment
            for segment in segments
            if segment.last_event_id > after_event_id
            or segment.last_attachment_id > after_attachment_id
        ]

        # collect data from the segments
        sample_data = SampleData(events=[], attachments=[])
        for segment in segments:
            data = self.read_segment_data(segment.id, id, epoch)
            sample_data.events.extend(data.events)
            sample_data.attachments.extend(data.attachments)

        return sample_data

    def _manifest_file(self) -> str:
        return f"{self._dir}{MANIFEST}"


def cleanup_sample_buffer_filestores(log_dir: str) -> None:
    # read log buffer dirs (bail if there is no buffer_dir)
    fs = filesystem(log_dir)
    buffer_dir = sample_buffer_dir(log_dir, fs)
    try:
        log_buffers = [
            buffer for buffer in fs.ls(buffer_dir) if buffer.type == "directory"
        ]
    except FileNotFoundError:
        return

    # for each buffer dir, confirm there is a running .eval file
    # (remove the buffer dir if there is no .eval or the eval is finished)
    for log_buffer in log_buffers:
        try:
            log_file = f"{log_dir}{fs.sep}{basename(log_buffer.name)}.{EVAL_LOG_FORMAT}"
            log_header = read_eval_log(log_file, header_only=True)
            if log_header.status != "started":
                cleanup_sample_buffer_filestore(log_buffer.name, fs)

        except FileNotFoundError:
            cleanup_sample_buffer_filestore(log_buffer.name, fs)

    # remove the .buffer dir if it's empty
    try:
        if len(fs.ls(buffer_dir)) == 0:
            fs.rm(buffer_dir, recursive=True)
    except FileNotFoundError:
        pass


def cleanup_sample_buffer_filestore(buffer_dir: str, fs: FileSystem) -> None:
    try:
        fs.rm(buffer_dir, recursive=True)
    except Exception as ex:
        logger.warning(
            f"Error cleaning up sample buffer database at {buffer_dir}: {ex}"
        )


def segment_name(id: int) -> str:
    return f"segment.{id}.zip"


def segment_file_name(id: str | int, epoch: int) -> str:
    return f"{id}_{epoch}.json"


def sample_buffer_dir(log_dir: str, fs: FileSystem | None = None) -> str:
    log_dir = log_dir.rstrip("/\\")
    fs = fs or filesystem(log_dir)
    return f"{log_dir}{fs.sep}.buffer"
