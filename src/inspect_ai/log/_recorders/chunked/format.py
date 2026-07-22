"""Entry naming, chunk math, and per-sample dispatch for chunked samples.

A chunked sample is an additive per-sample shape inside the ``.eval`` zip
(same extension, no format version bump — the shape is detected
structurally off the zip central directory). The sample lives under a
per-sample prefix as a small "shell" entry plus four flat,
index-addressed sequences, enabling random access within a sample. See
``design/large-samples.md`` (Part I) for the ratified format design.

Layout (per sample)::

    samples/{id}_epoch_{epoch}/sample.json
    samples/{id}_epoch_{epoch}/metadata.json      (only when non-empty)
    samples/{id}_epoch_{epoch}/skeleton.json
    samples/{id}_epoch_{epoch}/messages/{start}.json
    samples/{id}_epoch_{epoch}/events/{start}.json
    samples/{id}_epoch_{epoch}/events/stats.json
    samples/{id}_epoch_{epoch}/calls/{start}.json
    samples/{id}_epoch_{epoch}/attachments/{start}.json

Chunks are named by the index of their first item only — filenames
carry no range semantics (every range that appears in the data is
half-open ``[start, end_exclusive)``, and a name like ``0-50`` invites
inclusive misreading). Chunks are contiguous and complete, so the chunk
holding index ``i`` is the one with the greatest start <= ``i``; a
chunk's extent is the next chunk's start (the last chunk's end is the
sequence count, from the shell's ``sequences`` boundaries). Chunk size
is writer policy, not format: messages/events/calls chunk by item count,
attachments chunk by target byte size (contents vary from ~100B to MBs).

Attachments are a sequence of bare strings referenced from the other
sequences as ``attachment://<index>``. Identity is the sequence index;
content-hash dedup is a write-time policy, never persisted. Attachments
stay extracted (rather than inlined) because content dedups *across
containers* — the same text recurs in pooled messages, wire
request/response payloads, tool events, state deltas, and tool schemas.

One log can mix per-sample shapes: a monolith sample is today's single
entry (``samples/{id}_epoch_{epoch}.json``), a chunked sample is the
per-sample prefix. One name form per sample; readers classify each
sample off central-directory entry names (`classify_sample_shape`).
"""

from collections.abc import Container
from typing import Literal, NamedTuple

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_ATTACHMENTS_CHUNK_BYTES = 2 * 1024 * 1024

SAMPLES_DIR = "samples"
SHELL_JSON = "sample.json"
METADATA_JSON = "metadata.json"
SKELETON_JSON = "skeleton.json"
STATS_JSON = "stats.json"

MESSAGES_SEQUENCE = "messages"
EVENTS_SEQUENCE = "events"
CALLS_SEQUENCE = "calls"
ATTACHMENTS_SEQUENCE = "attachments"

SampleShape = Literal["monolith", "chunked"]


def sample_prefix(id: str | int, epoch: int) -> str:
    """Zip entry prefix under which all of a chunked sample's entries live."""
    return f"{SAMPLES_DIR}/{id}_epoch_{epoch}"


def shell_entry_name(id: str | int, epoch: int) -> str:
    return f"{sample_prefix(id, epoch)}/{SHELL_JSON}"


def metadata_entry_name(id: str | int, epoch: int) -> str:
    return f"{sample_prefix(id, epoch)}/{METADATA_JSON}"


def skeleton_entry_name(id: str | int, epoch: int) -> str:
    return f"{sample_prefix(id, epoch)}/{SKELETON_JSON}"


def events_stats_entry_name(id: str | int, epoch: int) -> str:
    """Per-chunk event stats sidecar (events sequence only).

    Lives inside the ``events/`` prefix — unlike ``skeleton.json``, stats
    are a function of chunking policy (rechunking invalidates them), so
    they sit with the chunks they describe. Chunk entry names are purely
    numeric, so ``stats.json`` can never collide with one.
    """
    return f"{sample_prefix(id, epoch)}/{EVENTS_SEQUENCE}/{STATS_JSON}"


def chunk_entry_name(id: str | int, epoch: int, sequence: str, start: int) -> str:
    return f"{sample_prefix(id, epoch)}/{sequence}/{start}.json"


def monolith_entry_name(id: str | int, epoch: int) -> str:
    """Today's single-entry sample name (mirrors `eval.py`'s `_sample_filename`).

    Defined locally (rather than imported) to keep this module free of
    `eval.py`'s heavy import graph; a test pins the two in sync.
    """
    return f"{SAMPLES_DIR}/{id}_epoch_{epoch}.json"


def classify_sample_shape(
    entry_names: Container[str], id: str | int, epoch: int
) -> SampleShape | None:
    """Classify a sample's on-disk shape off zip central-directory entry names.

    Dispatch is structural and per-sample: a monolith sample is today's
    single entry name, a chunked sample has a shell entry under its
    per-sample prefix. One name form exists per sample; a log can mix
    shapes across samples. Returns `None` when the sample is present in
    neither shape.
    """
    if monolith_entry_name(id, epoch) in entry_names:
        return "monolith"
    if shell_entry_name(id, epoch) in entry_names:
        return "chunked"
    return None


class ChunkRange(NamedTuple):
    """Half-open ``[start, end_exclusive)`` extent of one chunk."""

    start: int
    end_exclusive: int


def chunk_ranges(count: int, chunk_size: int) -> list[ChunkRange]:
    """Split ``count`` items into count-based chunk ranges."""
    return [
        ChunkRange(start, min(start + chunk_size, count))
        for start in range(0, count, chunk_size)
    ]


def chunk_boundaries(count: int, chunk_size: int) -> list[int]:
    """Cumulative end-exclusive chunk boundaries for count-based chunking.

    This is the shape the shell's ``sequences`` field carries: the last
    element is the sequence's total count; chunk entry starts are
    ``[0, *boundaries[:-1]]``.
    """
    return [range.end_exclusive for range in chunk_ranges(count, chunk_size)]


def attachment_chunk_boundaries(sizes: list[int], target_bytes: int) -> list[int]:
    """Size-based chunk boundaries: pack items until ~target_bytes per chunk.

    An item larger than ``target_bytes`` gets a chunk to itself. Returns
    cumulative end-exclusive boundaries (same shape as `chunk_boundaries`).
    """
    boundaries: list[int] = []
    chunk_bytes = 0
    for index, size in enumerate(sizes):
        if chunk_bytes and chunk_bytes + size > target_bytes:
            boundaries.append(index)
            chunk_bytes = 0
        chunk_bytes += size
    if chunk_bytes:
        boundaries.append(len(sizes))
    return boundaries


def boundary_ranges(boundaries: list[int]) -> list[ChunkRange]:
    """Cumulative end-exclusive boundaries -> half-open chunk ranges."""
    return [
        ChunkRange(start, end_exclusive)
        for start, end_exclusive in zip([0, *boundaries[:-1]], boundaries)
    ]
