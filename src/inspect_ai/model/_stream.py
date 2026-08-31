"""Streaming events for `Model.generate()`.

Public surface: the `StreamEvent` union and `StreamHandler` callback type
accepted by the `on_stream` parameter of `Model.generate()`.

Internal surface: a per-generate `ModelStreamObserver` that the model wrapper
installs via ContextVar around each provider attempt (the established
`_active_model_event` pattern). Provider streaming loops report each chunk
once through the module-level `report_model_stream_*` functions; the observer
fans out to its consumers (see the class docstring). Providers with an
auto/unset streaming setting consult `model_stream_requested()` in their
stream decision, so passing `on_stream` is by itself sufficient to enable
streaming. Providers that don't stream never call in, and callers that don't
pass `on_stream` still feed the progress record via bare heartbeats — both
degrade gracefully (see design/ctl/generate-progress.md).

To keep on_stream support code from ever affecting callers that didn't opt
in (a provider may stream for its own reasons — e.g. Anthropic auto-streams
long/reasoning requests), everything downstream of a content delta is gated
on an `on_stream` handler being present: providers gate delta construction
on `model_stream_requested()` (reporting a bare heartbeat instead), and
`ModelStreamObserver.report_delta` backstops the reporting side of any
ungated call site (construction itself can only be gated where it happens).
Without `on_stream` only the heartbeat/token progress channel runs —
partial-output snapshots included, since they are built from the delta
stream.
"""

import contextlib
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from logging import getLogger
from typing import TYPE_CHECKING, Awaitable, Callable, Iterator, Literal, Union

from pydantic import BaseModel, Field
from typing_extensions import TypeAlias

from inspect_ai._util.content import Content, ContentReasoning, ContentText

from ._chat_message import ChatMessageAssistant
from ._model_output import ChatCompletionChoice, ModelOutput

if TYPE_CHECKING:
    from inspect_ai.event._model import ModelEvent

logger = getLogger(__name__)


class StreamTextEvent(BaseModel):
    """Incremental text delta from a streaming model response."""

    type: Literal["text"] = Field(default="text")
    """Event type."""

    text: str
    """Text fragment (append to previously received text)."""


class StreamReasoningEvent(BaseModel):
    """Incremental reasoning delta from a streaming model response."""

    type: Literal["reasoning"] = Field(default="reasoning")
    """Event type."""

    reasoning: str
    """Reasoning fragment (append to previously received reasoning)."""


class StreamToolCallEvent(BaseModel):
    """Incremental tool call delta from a streaming model response."""

    type: Literal["tool_call"] = Field(default="tool_call")
    """Event type."""

    id: str | None = Field(default=None)
    """Identifier of the tool call the fragment belongs to (when reported)."""

    function: str | None = Field(default=None)
    """Name of the function being called (when reported)."""

    arguments: str = Field(default="")
    """Argument fragment (partial JSON — append to previously received
    fragments for the same call; complete JSON only once the call finishes)."""


class StreamRetryEvent(BaseModel):
    """The model call is being retried after a failed attempt.

    Emitted before any deltas from the new attempt when a prior attempt
    already delivered deltas: content received so far belongs to the failed
    attempt and should be discarded — the final `ModelOutput` is produced
    entirely by the attempt that succeeds.
    """

    type: Literal["retry"] = Field(default="retry")
    """Event type."""

    attempt: int
    """The attempt about to run (1-based; the first retry is attempt 2).
    A provider-internal retry that regenerates output within one attempt
    (e.g. a malformed-function-call retry) re-announces the current attempt
    number, so consecutive boundaries may carry the same value."""


StreamEvent = Union[
    StreamTextEvent, StreamReasoningEvent, StreamToolCallEvent, StreamRetryEvent
]
"""Incremental event delivered to `on_stream` during `Model.generate()`."""

StreamHandler: TypeAlias = Callable[[StreamEvent], Awaitable[None]]
"""Async callback receiving `StreamEvent`s during `Model.generate()`."""


StreamContentEvent: TypeAlias = Union[
    StreamTextEvent, StreamReasoningEvent, StreamToolCallEvent
]
"""Content delta reported by a provider streaming loop (internal)."""


class NoStreamDataError(RuntimeError):
    """A streaming response completed (HTTP 200) without delivering any data.

    Raised by provider streaming loops when a misbehaving server ends the
    stream with zero chunks. Always retried by the model layer's retry
    classifier (`Model.should_retry`) regardless of provider — an empty
    stream carries no signal to classify from, and failing the sample would
    score a server hiccup as an empty (wrong) completion. Subclass of
    `RuntimeError` so pre-existing `except RuntimeError` handling still
    applies.
    """


PARTIAL_OUTPUT_FLUSH_INTERVAL = 1.0
"""Minimum seconds between partial-output snapshot notifications.

Each flush re-serializes the pending event for transcript subscribers (the
realtime sample buffer persists a row per update), so per-chunk notification
is off the table (see the endpoint-cost-audit note in
design/ctl/generate-progress.md); one flush per second keeps inspect view's
live rendering fresh while bounding that cost for long generations.
"""


class ModelStreamObserver:
    """Fan-out hub for provider stream chunks during one `Model.generate()`.

    Created once per generate call (spanning retry attempts) and installed
    around each provider attempt via `model_stream_observer()`. Providers
    report each chunk once (the `report_model_stream_*` functions) and the
    observer projects it onto each consumer:

    - the pending `ModelEvent`'s progress record (cumulative output tokens +
      last-progress heartbeat), read by the control channel and TUI
      (design/ctl/generate-progress.md layer 2);
    - throttled partial `ModelOutput` snapshots on the pending event, so
      transcript subscribers (inspect view's realtime buffer) render output
      growing while the call is in flight;
    - the caller's `on_stream` callback (display-only: an exception it
      raises is logged and detaches it for the remainder of the call — see
      `_deliver` — never failing the model call itself).

    The last two are delta-driven and run only while an `on_stream` handler
    is attached (`report_delta` degrades to a heartbeat otherwise): they are
    on_stream support code, and a caller that never passed a callback must
    not be exposed to it. The progress record alone runs for every streamed
    call.

    The wrapper (not providers) owns retry semantics: `begin_attempt` resets
    per-attempt state and emits a `StreamRetryEvent` boundary to `on_stream`
    when an earlier attempt already delivered deltas, so accumulating
    consumers know to discard the failed attempt's prefix. Providers stay
    retry-oblivious; provider-internal continuations that reuse one attempt's
    stream position (e.g. Anthropic `pause_turn`) call
    `report_model_stream_start()` instead, which only rolls the token counter
    base — no boundary is emitted because the continuation extends the same
    logical output.
    """

    def __init__(
        self,
        model: str,
        on_stream: StreamHandler | None,
        publish_partial: bool = True,
    ) -> None:
        self._model = model
        self._on_stream = on_stream
        # partial-output snapshots notify transcript subscribers; the wrapper
        # passes False when a ModelEventSink is installed (the pending event
        # was routed to the sink, not the transcript — notifying would insert
        # a phantom pending event into the transcript's sidecar and buffer)
        self._publish_partial = publish_partial
        self._attempt = 0
        # deltas delivered to on_stream during any attempt so far — gates the
        # retry boundary (a consumer that never received a delta has nothing
        # to discard)
        self._delivered = False
        # per-attempt state (reset by begin_attempt)
        self._event: "ModelEvent | None" = None
        self._tokens_base = 0
        self._tokens_current: int | None = None
        # accumulated content deltas: (kind, fragments) runs, joined into
        # Content items at flush time (appending fragments keeps per-chunk
        # work O(1); string += on one growing block would be quadratic over
        # a long generation)
        self._fragments: list[tuple[str, list[str]]] = []
        self._partial_published = False
        self._last_flush = 0.0

    async def begin_attempt(self, event: "ModelEvent") -> None:
        """Bind the observer to a new attempt's pending event.

        Called by the wrapper before each provider attempt. Emits the
        `StreamRetryEvent` boundary eagerly — before the attempt runs rather
        than on its first delta — so it carries the current attempt number
        and is delivered even when the retried attempt streams no deltas
        (the consumer must still learn that the accumulated prefix is stale).
        """
        self._attempt += 1
        self._event = event
        self._reset_output_state()
        if self._attempt > 1 and self._delivered:
            await self._deliver(StreamRetryEvent(attempt=self._attempt))

    async def output_restarted(self) -> None:
        """A provider-internal retry is regenerating the current attempt's output.

        Unlike wrapper-level retries (fresh pending event, `begin_attempt`)
        or continuations that extend the same output (`stream_started`), a
        provider-internal retry (e.g. Google's malformed-function-call
        retry) replaces what has streamed so far while reusing the attempt's
        pending event. Reset the published partial snapshot (with
        notification, so live viewers drop it), the accumulation and token
        state — including the progress record's token count, which described
        the discarded stream (counts are never estimated, so `None` until the
        replacement stream reports usage) — and re-announce the current
        attempt to `on_stream` so accumulating consumers discard the
        replaced prefix.
        """
        self.discard_partial_output()
        event = self._event
        if event is not None and event._progress is not None:
            event._progress.output_tokens = None
        self._reset_output_state()
        if self._delivered:
            await self._deliver(StreamRetryEvent(attempt=max(self._attempt, 1)))

    def _reset_output_state(self) -> None:
        self._tokens_base = 0
        self._tokens_current = None
        self._fragments = []
        self._partial_published = False
        self._last_flush = 0.0

    def stream_started(self) -> None:
        """A provider response stream opened (or re-opened) for this attempt.

        Rolls the current stream's cumulative token count into the base so
        counts reported by the next stream add rather than overwrite —
        keeping the progress record monotonic across provider continuations
        and SDK-internal stream restarts within one attempt.
        """
        if self._tokens_current is not None:
            self._tokens_base += self._tokens_current
            self._tokens_current = None
        self._touch_progress()

    def report_progress(self, output_tokens: int | None = None) -> None:
        if output_tokens is not None:
            self._tokens_current = output_tokens
        self._touch_progress()

    async def report_delta(self, delta: StreamContentEvent) -> None:
        # without a live handler (never passed, or detached after raising)
        # deltas degrade to a bare heartbeat — no accumulation, no partial
        # snapshots. Backstops the reporting side of any ungated call site;
        # construction must still be gated at the call site (see the module
        # docstring).
        if self._on_stream is None:
            self._touch_progress()
            return
        self._accumulate(delta)
        self._touch_progress()
        self._maybe_flush_partial()
        self._delivered = True
        await self._deliver(delta)

    async def _deliver(self, event: StreamEvent) -> None:
        """Deliver one event to `on_stream`, detaching the handler if it raises.

        `on_stream` is a display-only side channel, so a handler exception
        must never fail (or, worse, retry) the paid model call — the same
        log-and-continue policy the hooks framework applies to observability
        callbacks. The first exception is logged with its traceback and the
        handler is detached for the remainder of this generate call (all
        attempts): after one dropped event the accumulated stream is no
        longer faithful, so going quiet — the caller falls back to the
        returned `ModelOutput` — beats delivering a corrupted stream. The
        next generate call constructs a fresh observer, so a transiently
        broken handler recovers there. Detaching also turns
        `model_stream_requested()` False for this call's later attempts
        (nothing consumes the deltas, so auto-mode providers needn't
        stream). Only `Exception` is caught — cancellation propagates.
        """
        if self._on_stream is None:
            return
        try:
            await self._on_stream(event)
        except Exception:
            self._on_stream = None
            logger.warning(
                "on_stream handler raised an exception; streaming callbacks "
                f"are disabled for the remainder of this {self._model} "
                "generate call",
                exc_info=True,
            )

    def discard_partial_output(self) -> None:
        """Reset a published partial snapshot the attempt no longer stands by.

        Called by the wrapper before completing the event with an error
        (and by `output_restarted` when a provider-internal retry replaces
        the streamed output) —
        `complete()` doesn't touch `event.output` on the error path, so
        without this an errored event would carry the failed attempt's
        partial output as if it were a real (empty-stop-reason) response.

        Notifies the transcript so live views (realtime buffer) drop the
        snapshot too. On the error paths this is redundant (`complete()`
        notifies right after), but on cancellation nothing else notifies —
        the event stays pending, so the buffer's last-written row would
        otherwise keep the failed attempt's partial output until the sample
        finalizes. Safe under cancellation: `_event_updated` is sync.
        `_partial_published` implies no ModelEventSink is installed, so the
        notification cannot leak a sink-withheld event into the transcript.
        """
        event = self._event
        if event is not None and self._partial_published:
            event.output = ModelOutput.from_content(event.model, "")
            self._partial_published = False
            if event.pending is True:
                from inspect_ai.log._transcript import transcript

                transcript()._event_updated(event)

    def _touch_progress(self) -> None:
        from inspect_ai.event._model import ModelEventProgress

        event = self._event
        if event is None or event.pending is not True:
            return
        progress = event._progress
        if progress is None:
            progress = ModelEventProgress()
            event._progress = progress
        progress.last_progress_at = datetime.now(timezone.utc).timestamp()
        if self._tokens_current is not None or self._tokens_base > 0:
            progress.output_tokens = self._tokens_base + (self._tokens_current or 0)

    def _accumulate(self, delta: StreamContentEvent) -> None:
        if isinstance(delta, StreamTextEvent):
            kind, fragment = "text", delta.text
        elif isinstance(delta, StreamReasoningEvent):
            kind, fragment = "reasoning", delta.reasoning
        else:
            # tool-call fragments are partial JSON — not renderable as
            # content, so they feed progress and on_stream but not the
            # snapshot
            return
        if self._fragments and self._fragments[-1][0] == kind:
            self._fragments[-1][1].append(fragment)
        else:
            self._fragments.append((kind, [fragment]))

    def _maybe_flush_partial(self) -> None:
        event = self._event
        if (
            not self._publish_partial
            or event is None
            or event.pending is not True
            or not self._fragments
        ):
            return
        now = time.monotonic()
        if (
            self._partial_published
            and now - self._last_flush < PARTIAL_OUTPUT_FLUSH_INTERVAL
        ):
            return
        self._last_flush = now
        self._partial_published = True
        content: list[Content] = [
            ContentText(text="".join(fragments))
            if kind == "text"
            else ContentReasoning(reasoning="".join(fragments))
            for kind, fragments in self._fragments
        ]
        event.output = ModelOutput(
            model=self._model,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=content,
                        model=self._model,
                        source="generate",
                    ),
                    stop_reason="unknown",
                )
            ],
        )
        from inspect_ai.log._transcript import transcript

        transcript()._event_updated(event)


_model_stream_observer: ContextVar[ModelStreamObserver | None] = ContextVar(
    "_model_stream_observer", default=None
)


@contextlib.contextmanager
def model_stream_observer(observer: ModelStreamObserver) -> Iterator[None]:
    """Install *observer* as the stream target for the enclosed provider call."""
    token = _model_stream_observer.set(observer)
    try:
        yield
    finally:
        _model_stream_observer.reset(token)


def model_stream_requested() -> bool:
    """True when the current generate call has an `on_stream` consumer.

    Providers whose streaming setting is auto/unset consult this in their
    stream decision so that passing `on_stream` to `Model.generate()` is by
    itself sufficient to enable streaming (an explicit provider-level
    streaming opt-out still wins). False when no observer is installed —
    the monitoring consumers alone never turn streaming on (see the
    non-goals in design/ctl/generate-progress.md).

    Provider streaming loops also consult this per chunk to gate delta
    construction/reporting: when a call streams for reasons other than
    `on_stream` (auto-streaming heuristics, an explicit streaming opt-in),
    the loop reports bare heartbeats instead, so on_stream support code
    never runs for callers that didn't pass a callback. Rechecking per chunk
    also stops delta work once a raising handler is detached mid-call.
    """
    observer = _model_stream_observer.get()
    return observer is not None and observer._on_stream is not None


def report_model_stream_start() -> None:
    """Report that a provider response stream opened (from a provider loop).

    Call at the top of each streaming loop — including re-opened streams
    within one generate attempt (provider continuations, SDK-internal stream
    restarts). Cumulative token counts reported after this call add to totals
    from earlier streams in the same attempt rather than overwriting them.
    No-op when no observer is installed (e.g. provider-internal generates
    that don't run under the model wrapper).
    """
    observer = _model_stream_observer.get()
    if observer is not None:
        observer.stream_started()


async def report_model_stream_restart() -> None:
    """Report a provider-internal retry that regenerates streamed output.

    For retries below the wrapper's retry loop (e.g. Google's
    malformed-function-call retry) where the response is re-generated
    within the same attempt: discards accumulated partial output and
    delivers a retry boundary to `on_stream` (re-announcing the current
    attempt number). For a re-opened stream that *extends* the same output
    (provider continuations), use `report_model_stream_start()` instead.
    No-op when no observer is installed.
    """
    observer = _model_stream_observer.get()
    if observer is not None:
        await observer.output_restarted()


def report_model_stream_progress(output_tokens: int | None = None) -> None:
    """Report progress on the in-flight model call (from a provider loop).

    Call per stream chunk. `output_tokens` is the cumulative output token
    count reported by the provider for the current stream when available,
    else `None` (a bare heartbeat — never fabricate an estimate; see
    design/ctl/generate-progress.md). Cheap attribute writes, so no
    throttling is needed at call sites. No-op when no observer is installed.
    """
    observer = _model_stream_observer.get()
    if observer is not None:
        observer.report_progress(output_tokens)


async def report_model_stream_delta(delta: StreamContentEvent) -> None:
    """Report a content delta (from a provider streaming loop).

    Call sites must gate on `model_stream_requested()` (reporting a bare
    heartbeat instead when it is False) so that delta construction never
    runs for callers without an `on_stream` handler. When a handler is
    attached this feeds every consumer at once: progress heartbeat, the
    partial-output snapshot, and the caller's `on_stream` callback (awaited
    here, so a slow consumer applies natural backpressure to the stream
    read; an exception it raises is logged and detaches the callback for
    the remainder of the generate call — see `ModelStreamObserver._deliver`).
    Degrades to a bare heartbeat without a handler; no-op when no observer
    is installed.
    """
    observer = _model_stream_observer.get()
    if observer is not None:
        await observer.report_delta(delta)
