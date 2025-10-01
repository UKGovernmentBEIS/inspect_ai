from collections.abc import Set as AbstractSet
from typing import (
    AsyncIterator,
    Awaitable,
    Callable,
    NamedTuple,
    Protocol,
)

from .._recorder.recorder import ScanRecorder
from .._scanner.result import ResultReport
from .._scanner.scanner import Scanner
from .._scanner.types import ScannerInput
from .._transcript.types import Transcript, TranscriptInfo


class ParseJob(NamedTuple):
    """Represents a unit of work for parsing/filtering a transcript in preparation for scanning with multiple scanners."""

    transcript_info: TranscriptInfo
    """Metadata identifying which transcript to process."""

    scanner_indices: AbstractSet[int]
    """Indices into the scanner list indicating which scanners need to process this transcript."""


class ScannerJob(NamedTuple):
    """Represents a unit of work for filtering a union transcript and scanning it with a specific scanner."""

    union_transcript: Transcript
    """Transcript pre-filtered with the union of ALL scanners' content filters.

    This contains a superset of the data needed by all scanners and typically needs
    to be filtered again per-scanner (based on that scanner's specific content filter)
    before being passed to the scanner.
    """

    scanner: Scanner[ScannerInput]
    """The specific scanner to apply to the (further filtered) transcript."""


class ConcurrencyStrategy(Protocol):
    """Callable strategy interface (Strategy Pattern) for executing scanner work.

    This callable protocol allows either a plain async function or a class with
    an ``__call__`` coroutine method to serve as a concurrency strategy.

    Implementations control HOW work items are scheduled and executed while the
    caller supplies WHAT to execute through the `item_processor` callback.
    """

    async def __call__(
        self,
        *,
        parse_jobs: AsyncIterator[ParseJob],
        parse_function: Callable[[ParseJob], Awaitable[list[ScannerJob]]],
        scan_function: Callable[[ScannerJob], Awaitable[list[ResultReport]]],
        recorder: ScanRecorder,
        bump_progress: Callable[[], None],
    ) -> None: ...
