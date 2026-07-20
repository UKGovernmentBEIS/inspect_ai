import os
import tempfile
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeAlias
from urllib.parse import urlparse
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import override

from inspect_ai._display.core.display import TaskDisplayMetric
from inspect_ai._util.constants import DEFAULT_LOG_SHARED, EVAL_LOG_FORMAT
from inspect_ai._util.file import FileSystem, basename, dirname, filesystem, open_file
from inspect_ai._util.json import to_json_safe, to_json_str_safe
from inspect_ai._util.zipfile import zipfile_compress_kwargs
from inspect_ai.log._file import read_eval_log

from ..._log import EvalSampleSummary
from .types import SampleBuffer, SampleData, Samples, TranscriptEventSink

if TYPE_CHECKING:
    from .history import SampleHistory


logger = getLogger(__name__)


class Segment(BaseModel):
    id: int
    last_event_id: int
    last_attachment_id: int
    last_message_pool_id: int = 0
    last_call_pool_id: int = 0


class SampleSegment(Segment):
    # Same shape as Segment, but scoped to one sample's contribution.
    pass


SampleSegmentEntry: TypeAlias = int | SampleSegment


class SegmentFile(BaseModel):
    id: str | int
    epoch: int
    data: SampleData


class SampleManifest(BaseModel):
    summary: EvalSampleSummary
    segments: list[SampleSegmentEntry] = Field(default_factory=list)


class Manifest(BaseModel):
    model_config = ConfigDict(ser_json_inf_nan="constants")

    metrics: list[TaskDisplayMetric] = Field(default_factory=list)
    samples: list[SampleManifest] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)


def _find_sample(
    manifest: Manifest, id: str | int, epoch: int
) -> SampleManifest | None:
    # `Sample.id` is `int | str` and the type as written round-trips through
    # the manifest, so the manifest may carry either form. URL handlers always
    # pass `id` as `str`; compare in string form so both directions match.
    id_str = str(id)
    return next(
        (
            s
            for s in manifest.samples
            if str(s.summary.id) == id_str and s.summary.epoch == epoch
        ),
        None,
    )


def sample_segment_id(segment: SampleSegmentEntry) -> int:
    return segment if isinstance(segment, int) else segment.id


def sample_segment_cursor(
    segment: SampleSegmentEntry, segments_by_id: dict[int, Segment]
) -> Segment | None:
    if isinstance(segment, SampleSegment):
        return segment
    return segments_by_id.get(segment)


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
    last_*_id values exceeds the corresponding cursor. Over-inclusive
    by design; individual items must be post-filtered by the caller.
    Legacy integer entries fall back to global segment maxima. That preserves
    compatibility but can over-include old co-batched manifests.

    Cursors are floored at 0 because SQL AUTOINCREMENT ids start at 1,
    so a cursor of `None`, `-1`, or `0` are equivalent: "no items of
    this type seen". A segment whose `last_*_id` is `0` (the writer's
    "no items of this type in this segment" sentinel; pool dimensions
    default to `0` per the Segment schema) then evaluates `0 > 0 = False`
    and drops out. Without the floor the initial client cursor of `-1`
    keeps every empty-pool segment qualifying forever, and the
    streaming viewer loops within `max-segments`.
    """
    after_event = max(0, after_event_id or 0)
    after_attachment = max(0, after_attachment_id or 0)
    after_message_pool = max(0, after_message_pool_id or 0)
    after_call_pool = max(0, after_call_pool_id or 0)

    segments_by_id = {s.id: s for s in manifest.segments}
    matching: list[Segment] = []
    seen_ids: set[int] = set()
    for sample_segment in sample.segments:
        segment_id = sample_segment_id(sample_segment)
        if segment_id in seen_ids:
            continue
        segment = segments_by_id.get(segment_id)
        if segment is None:
            continue
        cursor = (
            sample_segment if isinstance(sample_segment, SampleSegment) else segment
        )
        if (
            cursor.last_event_id > after_event
            or cursor.last_attachment_id > after_attachment
            or cursor.last_message_pool_id > after_message_pool
            or cursor.last_call_pool_id > after_call_pool
        ):
            seen_ids.add(segment_id)
            matching.append(segment)

    return sorted(matching, key=lambda s: s.id)


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


def _is_s3_tagging_denied(ex: Exception) -> bool:
    """Whether a failed S3 write was rejected for lacking object-tagging permission.

    Tagging an object on write (the ``x-amz-tagging`` header) requires
    ``s3:PutObjectTagging`` in addition to ``s3:PutObject``. s3fs maps an S3
    ``AccessDenied`` to ``PermissionError`` and preserves the underlying botocore
    error (which names the denied action, e.g. ``PutObjectTagging``) on the
    exception chain. Match either signal without taking a botocore dependency.
    """
    seen: set[int] = set()
    cur: BaseException | None = ex
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, PermissionError):
            return True
        text = str(cur).lower()
        if "accessdenied" in text or "tagging" in text:
            return True
        cur = cur.__cause__ or cur.__context__
    return False


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

        # Tag the ephemeral buffer objects synced to S3 (see _write_bytes for the
        # permission fallback).
        self._write_fs_options: dict[str, Any] = (
            {"s3_additional_kwargs": {"Tagging": "inspect-ephemeral=true"}}
            if urlparse(location).scheme == "s3"
            else {}
        )

        if create:
            self._fs.mkdir(self._dir, exist_ok=True)

            # place a file in the dir to force it to be created
            self._write_bytes(f"{self._dir}.keep", b"")

    def _write_bytes(self, path: str, data: bytes) -> None:
        """Write bytes to the filestore, tagging S3 objects as ephemeral.

        S3 buffer objects are written with an ``inspect-ephemeral`` tag so they
        can be expired by an S3 lifecycle rule. Tagging on write requires the
        ``s3:PutObjectTagging`` permission in addition to ``s3:PutObject``; if a
        tagged write is denied for lacking it, disable tagging for the remainder
        of this session and retry untagged so shared-log sync keeps working (the
        objects simply won't be lifecycle-expirable by tag).
        """
        try:
            with open_file(path, "wb", fs_options=self._write_fs_options) as f:
                f.write(data)
        except Exception as ex:
            if not self._write_fs_options or not _is_s3_tagging_denied(ex):
                raise
            logger.warning(
                "S3 object tagging denied when writing shared buffer objects "
                "(missing s3:PutObjectTagging?); continuing untagged for the rest "
                "of this session. Tag-based S3 lifecycle expiration will not apply "
                "to this run's buffer objects. (%s)",
                ex,
            )
            self._write_fs_options = {}
            with open_file(path, "wb") as f:
                f.write(data)

    def write_manifest(self, manifest: Manifest) -> None:
        self._write_bytes(self._manifest_file(), to_json_safe(manifest))

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

        try:
            with open(name, "rb") as zf:
                self._write_bytes(f"{self._dir}{segment_name(id)}", zf.read())
        finally:
            os.unlink(name)

    def read_manifest(self) -> Manifest | None:
        try:
            with open_file(self._manifest_file(), "r") as f:
                contents = f.read()
                return Manifest.model_validate_json(contents)
        except FileNotFoundError:
            return None

    def read_segment_data(
        self, id: int, sample_id: str | int, epoch_id: int
    ) -> SampleData:
        segment_file = f"{self._dir}{segment_name(id)}"
        with open_file(segment_file, "rb") as f:
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
        sample = _find_sample(manifest, id, epoch)
        if sample is None:
            return

        sample_segment_ids = {sample_segment_id(segment) for segment in sample.segments}
        for segment in sorted(manifest.segments, key=lambda s: s.id):
            if segment.id not in sample_segment_ids:
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
        sample = _find_sample(manifest, id, epoch)
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

    @override
    def sample_event_count(self, id: str | int, epoch: int) -> int:
        raise NotImplementedError("Sample history is only available for buffer DBs")

    @override
    def sample_has_event(self, id: str | int, epoch: int, event_id: str) -> bool:
        raise NotImplementedError("Sample history is only available for buffer DBs")

    @override
    def export_transcript_events(
        self, id: str | int, epoch: int, transcript_store: TranscriptEventSink
    ) -> int:
        raise NotImplementedError("Sample history is only available for buffer DBs")

    @override
    def open_sample_history_tail(
        self,
        id: str | int,
        epoch: int,
        n: int,
    ) -> AbstractContextManager["SampleHistory"]:
        raise NotImplementedError("Sample history is only available for buffer DBs")

    @override
    def open_sample_history_from(
        self,
        id: str | int,
        epoch: int,
        start: int,
        limit: int | None = None,
    ) -> AbstractContextManager["SampleHistory"]:
        raise NotImplementedError("Sample history is only available for buffer DBs")

    @override
    def open_sample_history(
        self,
        id: str | int,
        epoch: int,
    ) -> AbstractContextManager["SampleHistory"]:
        raise NotImplementedError("Sample history is only available for buffer DBs")

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

        sample = _find_sample(manifest, id, epoch)
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
