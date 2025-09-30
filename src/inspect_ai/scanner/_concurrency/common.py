from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, NamedTuple, Protocol

from .._recorder.recorder import ScanRecorder
from .._scanner.result import ResultReport
from .._scanner.scanner import Scanner
from .._scanner.types import ScannerInput
from .._transcript.types import TranscriptContent, TranscriptInfo


class WorkItem(NamedTuple):
    """Represents a unit of work for reading a transcript and scanning with multiple scanners.

    This groups all scanners that need to process the same transcript, allowing
    the transcript to be loaded once and reused across scanners within a single
    worker process.
    """

    transcript_info: TranscriptInfo
    union_content: TranscriptContent
    scanners: list[Scanner[ScannerInput]]


class ConcurrencyStrategy(Protocol):  # pragma: no cover - interface
    """Callable strategy interface (Strategy Pattern) for executing scanner work.

    This callable protocol allows either a plain async function or a class with
    an ``__call__`` coroutine method to serve as a concurrency strategy.

    Implementations control HOW work items are scheduled and executed while the
    caller supplies WHAT to execute through the `item_processor` callback.
    """

    async def __call__(
        self,
        *,
        recorder: ScanRecorder,
        work_items: AsyncIterator[WorkItem],
        item_processor: Callable[[WorkItem], Awaitable[dict[str, list[ResultReport]]]],
        bump_progress: Callable[[], None],
    ) -> None: ...
