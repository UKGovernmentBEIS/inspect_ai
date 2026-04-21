import os
import tempfile
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Iterator, Literal
from zipfile import ZipFile

from pydantic import BaseModel, Field
from typing_extensions import override

from inspect_ai._display.core.display import TaskDisplayMetric
from inspect_ai._util.constants import DEFAULT_LOG_SHARED, EVAL_LOG_FORMAT
from inspect_ai._util.file import FileSystem, basename, dirname, file, filesystem
from inspect_ai._util.json import to_json_safe, to_json_str_safe
from inspect_ai._util.zipfile import zipfile_compress_kwargs
from inspect_ai.log._file import read_eval_log

from ..._log import EvalSampleSummary
from .types import SampleBuffer, SampleData, Samples

logger = getLogger(__name__)


class Segment(BaseModel):
    id: int
    last_event_id: int
    last_attachment_id: int
    last_message_pool_id: int = 0
    last_call_pool_id: int = 0


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


def segments_for_sample_cursor(
    manifest: Manifest,
    sample: SampleManifest,
    *,
    after_event_id: int | None,
    after_attachment_id: int | None,
    after_message_pool_id: int | None,
    after_call_pool_id: int | None,
) -> list[Segment]:
    """Return segments for `sample` that can contain data newer than the cursors.

    OR-logic across cursor types: a segment qualifies if any of its
    last_*_id values exceeds the corresponding cursor. `None` is treated
    as `-1` (no cursor yet). Over-inclusive by design; individual items
    must be post-filtered by the caller.
    """
    after_event = after_event_id if after_event_id is not None else -1
    after_attachment = after_attachment_id if after_attachment_id is not None else -1
    after_message_pool = (
        after_message_pool_id if after_message_pool_id is not None else -1
    )
    after_call_pool = after_call_pool_id if after_call_pool_id is not None else -1

    by_id = sorted(
        (s for s in manifest.segments if s.id in sample.segments),
        key=lambda s: s.id,
    )
    return [
        s
        for s in by_id
        if s.last_event_id > after_event
        or s.last_attachment_id > after_attachment
        or s.last_message_pool_id > after_message_pool
        or s.last_call_pool_id > after_call_pool
    ]


@dataclass(frozen=True)
class SegmentLocation:
    """Location of a segment zip and the member to read from it."""

    id: int
    path: str
    member_name: str


@dataclass(frozen=True)
class PendingSampleSegments:
    """Segments + manifest metadata needed to fulfill a pending-sample query."""

    segments: list[SegmentLocation]
    has_more: bool
    complete: bool


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
            with ZipFile(segment_file, mode="w", **zipfile_compress_kwargs) as zip:
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

    def iter_sample_segments(
        self,
        id: str | int,
        epoch: int,
        manifest: Manifest,
    ) -> Iterator[tuple[int, SampleData]]:
        """Yield (segment_id, data) for each segment of a sample.

        Segments that fail to read (missing, corrupt) are logged as
        warnings and skipped.

        Args:
            id: Sample id.
            epoch: Sample epoch.
            manifest: The parsed manifest (avoids re-reading it per call).

        Yields:
            Tuples of (segment_id, SampleData) for each successfully read
            segment, in segment-id order.
        """
        sample = next(
            (
                s
                for s in manifest.samples
                if s.summary.id == id and s.summary.epoch == epoch
            ),
            None,
        )
        if sample is None:
            return

        for segment in sorted(manifest.segments, key=lambda s: s.id):
            if segment.id not in sample.segments:
                continue
            try:
                data = self.read_segment_data(segment.id, id, epoch)
                yield (segment.id, data)
            except Exception as ex:
                logger.warning(f"Skipping segment {segment.id}: {ex}")

    @override
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
        after_message_pool_id: int | None = None,
        after_call_pool_id: int | None = None,
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

        segments = segments_for_sample_cursor(
            manifest,
            sample,
            after_event_id=after_event_id,
            after_attachment_id=after_attachment_id,
            after_message_pool_id=after_message_pool_id,
            after_call_pool_id=after_call_pool_id,
        )

        # defaults for the per-item post-filter below
        after_event_id = after_event_id if after_event_id is not None else -1
        after_attachment_id = (
            after_attachment_id if after_attachment_id is not None else -1
        )
        after_message_pool_id = (
            after_message_pool_id if after_message_pool_id is not None else -1
        )
        after_call_pool_id = (
            after_call_pool_id if after_call_pool_id is not None else -1
        )

        # collect data from the segments
        try:
            sample_data = SampleData(
                events=[], attachments=[], message_pool=[], call_pool=[]
            )
            for segment in segments:
                data = self.read_segment_data(segment.id, id, epoch)
                sample_data.events.extend(data.events)
                sample_data.attachments.extend(data.attachments)
                sample_data.message_pool.extend(data.message_pool)
                sample_data.call_pool.extend(data.call_pool)
        except FileNotFoundError:
            # the sample might complete while this is running, in which case
            # we'll just return None
            return None

        # The segment-level OR-filter above includes entire segments when any
        # cursor type has new data, so individual items already seen by the
        # client may be included. Post-filter to exclude them.
        sample_data.events = [e for e in sample_data.events if e.id > after_event_id]
        sample_data.attachments = [
            a for a in sample_data.attachments if a.id > after_attachment_id
        ]
        sample_data.message_pool = [
            m for m in sample_data.message_pool if m.id > after_message_pool_id
        ]
        sample_data.call_pool = [
            c for c in sample_data.call_pool if c.id > after_call_pool_id
        ]

        return sample_data

    def get_pending_segments(
        self,
        id: str | int,
        epoch: int,
        *,
        after_event_id: int | None = None,
        after_attachment_id: int | None = None,
        after_message_pool_id: int | None = None,
        after_call_pool_id: int | None = None,
        max_segments: int | None = None,
        tail: bool = False,
    ) -> PendingSampleSegments | None:
        """Return segment locations + metadata for a pending-sample query.

        Returns None when the manifest is missing or the requested sample is
        not in the manifest. With `max_segments >= 0`, the result is truncated
        and `has_more` is set; otherwise all eligible segments are returned
        and `has_more` is False.

        With `tail=True`, the truncation takes the last `max_segments` segments
        instead of the first; `has_more` is always False so a "show recent then
        follow" caller can drop in mid-stream without cursor management.
        """
        manifest = self.read_manifest()
        if manifest is None:
            return None

        sample = next(
            (
                s
                for s in manifest.samples
                if s.summary.id == id and s.summary.epoch == epoch
            ),
            None,
        )
        if sample is None:
            return None

        all_segments = segments_for_sample_cursor(
            manifest,
            sample,
            after_event_id=after_event_id,
            after_attachment_id=after_attachment_id,
            after_message_pool_id=after_message_pool_id,
            after_call_pool_id=after_call_pool_id,
        )
        if max_segments is not None and max_segments >= 0:
            segments = (
                all_segments[-max_segments:] if tail else all_segments[:max_segments]
            )
        else:
            segments = all_segments
        has_more = False if tail else len(segments) < len(all_segments)

        member_name = segment_file_name(sample.summary.id, sample.summary.epoch)
        locations = [
            SegmentLocation(
                id=seg.id,
                path=f"{self._dir}{segment_name(seg.id)}",
                member_name=member_name,
            )
            for seg in segments
        ]
        return PendingSampleSegments(
            segments=locations,
            has_more=has_more,
            complete=sample.summary.completed or False,
        )

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
