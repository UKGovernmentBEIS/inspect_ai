"""Entry naming and chunking for the experimental `.eval2` log format.

`.eval2` is a zip (zstd-compressed entries, like `.eval`) where each
sample's high-scale sequences (messages, events, calls) are stored as
range-named chunk entries alongside a small "shell" entry, enabling
random access within a sample. See
``design/plans/sample-data-pagination.md`` for the format design.

Layout (per sample)::

    samples/{id}_epoch_{epoch}/sample.json
    samples/{id}_epoch_{epoch}/messages/{start}-{end_exclusive}.json
    samples/{id}_epoch_{epoch}/events/{start}-{end_exclusive}.json
    samples/{id}_epoch_{epoch}/calls/{start}-{end_exclusive}.json

Chunk names are zero-padded so a lexicographic sort of entry names is
also an index sort (readers binary-search the central directory).
Chunk size is writer policy, not format: readers derive index→chunk
mapping purely from the range-encoded names.
"""

EVAL2_LOG_FILE_EXTENSION = ".eval2"

DEFAULT_CHUNK_SIZE = 1000

SAMPLES_DIR = "samples"
SHELL_JSON = "sample.json"

MESSAGES_SEQUENCE = "messages"
EVENTS_SEQUENCE = "events"
CALLS_SEQUENCE = "calls"

_RANGE_DIGITS = 10


def sample_prefix(id: str | int, epoch: int) -> str:
    """Zip entry prefix under which all of a sample's entries live."""
    return f"{SAMPLES_DIR}/{id}_epoch_{epoch}"


def shell_entry_name(id: str | int, epoch: int) -> str:
    return f"{sample_prefix(id, epoch)}/{SHELL_JSON}"


def chunk_entry_name(
    id: str | int, epoch: int, sequence: str, start: int, end_exclusive: int
) -> str:
    return (
        f"{sample_prefix(id, epoch)}/{sequence}/"
        f"{start:0{_RANGE_DIGITS}d}-{end_exclusive:0{_RANGE_DIGITS}d}.json"
    )


def chunk_ranges(count: int, chunk_size: int) -> list[tuple[int, int]]:
    """Split ``count`` items into ``(start, end_exclusive)`` chunk ranges."""
    return [
        (start, min(start + chunk_size, count)) for start in range(0, count, chunk_size)
    ]
