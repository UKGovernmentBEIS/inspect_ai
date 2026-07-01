from collections.abc import Awaitable, Callable

from inspect_ai._control.eval_state import BufferConfig
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.log._transcript import TranscriptHistoryProvider


class FakeLiveEvalData:
    """Adapts individual accessor callables into the ``LiveEvalData`` protocol.

    A test wires only the accessor(s) it exercises (e.g. just ``flush``); the
    rest default to an empty / no-op result. Stands in for the real
    ``TaskLogger`` that the runner hands to ``register_eval`` as
    ``EvalState.live``.
    """

    def __init__(
        self,
        *,
        summaries: Callable[[], Awaitable[list[EvalSampleSummary] | None]]
        | None = None,
        sample: Callable[..., Awaitable[EvalSample | None]] | None = None,
        events: Callable[[str | int, int], TranscriptHistoryProvider | None]
        | None = None,
        flush: Callable[[], Awaitable[int]] | None = None,
        buffer: Callable[[int | None, int | None], BufferConfig] | None = None,
    ) -> None:
        self._summaries = summaries
        self._sample = sample
        self._events = events
        self._flush = flush
        self._buffer = buffer

    async def sample_summaries(self) -> list[EvalSampleSummary] | None:
        return await self._summaries() if self._summaries is not None else None

    async def read_sample(
        self,
        id: str | int,
        epoch: int,
        *,
        exclude_fields: set[str] | None = None,
    ) -> EvalSample | None:
        if self._sample is None:
            return None
        return await self._sample(id, epoch, exclude_fields=exclude_fields)

    def sample_events_provider(
        self, id: str | int, epoch: int
    ) -> TranscriptHistoryProvider | None:
        return self._events(id, epoch) if self._events is not None else None

    async def flush_samples(self) -> int:
        return await self._flush() if self._flush is not None else 0

    def buffer_config(
        self, log_buffer: int | None = None, log_shared: int | None = None
    ) -> BufferConfig:
        if self._buffer is None:
            raise AssertionError("buffer_config called on a fake without a buffer")
        return self._buffer(log_buffer, log_shared)
