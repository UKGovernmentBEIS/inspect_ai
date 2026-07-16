"""Entry naming and chunking for the experimental `.eval2` log format.

`.eval2` is a zip (zstd-compressed entries, like `.eval`) where each
sample's high-scale sequences (messages, events, calls) are stored as
range-named chunk entries alongside a small "shell" entry, enabling
random access within a sample. See
``design/plans/sample-data-pagination.md`` for the format design.

Layout (per sample)::

    samples/{id}_epoch_{epoch}/sample.json
    samples/{id}_epoch_{epoch}/metadata.json
    samples/{id}_epoch_{epoch}/messages/{start}.json
    samples/{id}_epoch_{epoch}/events/{start}.json
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
"""

EVAL2_LOG_FILE_EXTENSION = ".eval2"

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_ATTACHMENTS_CHUNK_BYTES = 2 * 1024 * 1024

SAMPLES_DIR = "samples"
SHELL_JSON = "sample.json"
METADATA_JSON = "metadata.json"

MESSAGES_SEQUENCE = "messages"
EVENTS_SEQUENCE = "events"
CALLS_SEQUENCE = "calls"
ATTACHMENTS_SEQUENCE = "attachments"


def sample_prefix(id: str | int, epoch: int) -> str:
    """Zip entry prefix under which all of a sample's entries live."""
    return f"{SAMPLES_DIR}/{id}_epoch_{epoch}"


def shell_entry_name(id: str | int, epoch: int) -> str:
    return f"{sample_prefix(id, epoch)}/{SHELL_JSON}"


def metadata_entry_name(id: str | int, epoch: int) -> str:
    return f"{sample_prefix(id, epoch)}/{METADATA_JSON}"


def chunk_entry_name(id: str | int, epoch: int, sequence: str, start: int) -> str:
    return f"{sample_prefix(id, epoch)}/{sequence}/{start}.json"


def chunk_ranges(count: int, chunk_size: int) -> list[tuple[int, int]]:
    """Split ``count`` items into ``(start, end_exclusive)`` chunk ranges."""
    return [
        (start, min(start + chunk_size, count)) for start in range(0, count, chunk_size)
    ]
