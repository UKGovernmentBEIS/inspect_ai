"""Shared sample buffer reads: manifests and segments.

A worker run with ``--log-shared`` syncs its buffered samples to
``.buffer/<stem>/`` beside its log: ``manifest.json`` (one row per sample
still in its buffer database, with the segments holding its data) and one
``segment.<n>.zip`` per sync. Everything here reads through
``AsyncFilesystem`` and derives every path from the listed log name and the
manifest's integer segment ids; nothing is written (constructing a
``SampleBufferFilestore`` would write a ``.keep`` object). See "What the log
directory holds while a run is live" and "Per-sample reads" in
``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

import functools
import io
import struct
import zipfile
import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
import zstandard
from pydantic import ValidationError

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai.event._pool import resolve_model_event_calls, resolve_model_event_inputs
from inspect_ai.event._validate import validate_events
from inspect_ai.log._recorders.buffer.filestore import (
    MANIFEST,
    Manifest,
    SampleManifest,
    sample_segment_id,
    segment_file_name,
    segment_name,
)
from inspect_ai.log._recorders.buffer.types import SampleData
from inspect_ai.log._recover._reconstruct import (
    _deserialize_call_pool,
    _deserialize_message_pool,
    collapse_event_versions,
)

from .consistency import MAX_REREADS, LogUnparseableError
from .select import SampleKey

if TYPE_CHECKING:
    from inspect_ai.event._event import Event

    from .walk import LogFile

# Segment reads in flight at once, the CLI's fan-out cap.
_MAX_CONCURRENT_SEGMENTS = 32

_SEGMENT_READ_ERRORS = (
    zipfile.BadZipFile,
    KeyError,
    ValidationError,
    zlib.error,
    zstandard.ZstdError,
    struct.error,
    EOFError,
)


@dataclass(frozen=True)
class BufferSnapshot:
    """One read of a member's shared-buffer manifest."""

    location: str
    """The member's ``.buffer/<stem>/`` directory, with a trailing ``/``."""

    manifest: Manifest

    samples: dict[SampleKey, SampleManifest]
    """The manifest's sample rows by key (last row wins)."""

    mtime: float | None
    """The manifest's Last-Modified, in seconds."""


def buffer_location(file: LogFile) -> str | None:
    """The log's ``.buffer/<stem>/`` directory, when the walk saw a ``.buffer/`` beside it."""
    if file.buffer_dir is None:
        return None
    stem = file.name.rsplit(".", 1)[0]
    return f"{file.buffer_dir}/{stem}/"


async def read_manifest(fs: AsyncFilesystem, file: LogFile) -> BufferSnapshot | None:
    """Read the log's manifest, or ``None`` when it has none.

    A local manifest is rewritten in place on every sync, so a read can see
    it part-written: one that does not parse is re-read up to
    :data:`~.consistency.MAX_REREADS` times.

    Raises:
        LogUnparseableError: the manifest kept failing to parse.
    """
    location = buffer_location(file)
    if location is None:
        return None
    path = f"{location}{MANIFEST}"
    last: ValidationError | None = None
    for _ in range(MAX_REREADS + 1):
        try:
            content = await fs.read_file_info(path)
        except FileNotFoundError:
            return None
        try:
            manifest = Manifest.model_validate_json(content.data)
        except ValidationError as ex:
            last = ex
            continue
        return BufferSnapshot(
            location=location,
            manifest=manifest,
            samples={
                SampleKey(str(s.summary.id), s.summary.epoch): s
                for s in manifest.samples
            },
            mtime=content.mtime / 1000 if content.mtime is not None else None,
        )
    assert last is not None
    raise LogUnparseableError(path, str(last))


def segment_ids(sample: SampleManifest) -> list[int]:
    """The ids of every segment the manifest lists for ``sample``, in order."""
    return sorted({sample_segment_id(segment) for segment in sample.segments})


async def read_sample_data(
    fs: AsyncFilesystem, buffer: BufferSnapshot, sample: SampleManifest
) -> SampleData:
    """Every segment's rows for ``sample``, concatenated in segment order.

    Pooled references can point into earlier segments, so a correct event
    list needs the sample's whole segment history.

    Raises:
        FileNotFoundError: a segment is gone (the worker removed its buffer
            after its final flush).
        LogUnparseableError: a segment is not a zip holding the sample's rows
            (segments are written once, before the manifest that lists them,
            so this is not a torn read).
    """
    member = segment_file_name(sample.summary.id, sample.summary.epoch)
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_SEGMENTS)

    async def read(segment_id: int) -> SampleData:
        path = f"{buffer.location}{segment_name(segment_id)}"
        async with limiter:
            data = await fs.read_file(path)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                return SampleData.model_validate_json(zf.read(member))
        except _SEGMENT_READ_ERRORS as ex:
            raise LogUnparseableError(path, str(ex) or type(ex).__name__) from ex

    parts = await tg_collect(
        [functools.partial(read, segment_id) for segment_id in segment_ids(sample)]
    )
    merged = SampleData(events=[], attachments=[], message_pool=[], call_pool=[])
    for part in parts:
        merged.events.extend(part.events)
        merged.attachments.extend(part.attachments)
        merged.message_pool.extend(part.message_pool)
        merged.call_pool.extend(part.call_pool)
    return merged


def buffered_events(data: SampleData) -> list[Event]:
    """The sample's events as the recovery reconstruction builds them.

    Superseded versions of one event (a pending event rewritten when it
    resolves) collapse to the latest, and pooled model inputs and calls are
    resolved, as reading the flushed sample does. Attachments stay as
    ``attachment://`` references, as in the logged sample's events.
    """
    events = validate_events(
        [row.event for row in collapse_event_versions(data.events)]
    )
    events = resolve_model_event_inputs(
        events, _deserialize_message_pool(data.message_pool)
    )
    return resolve_model_event_calls(events, _deserialize_call_pool(data.call_pool))
