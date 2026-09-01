"""Tests for `Model.generate()` streaming callbacks (`on_stream`).

Providers report stream chunks into a shared observer installed by the model
wrapper (`inspect_ai.model._stream`); these tests drive that contract with a
scripted stub provider: delta delivery to `on_stream`, wrapper-owned retry
boundaries, partial-output snapshots on the pending event, and the pending
event's progress record (design/ctl/generate-progress.md layer 2).
"""

import json
from typing import Any, Callable, Coroutine

import anyio
import pytest
import tenacity
from tenacity.wait import WaitBaseT
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_grok,
    skip_if_no_openai,
)

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai._util.registry import _registry
from inspect_ai.event._model import ModelEvent, model_event_progress
from inspect_ai.log._samples import _active_model_event
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    StreamEvent,
    StreamReasoningEvent,
    StreamRetryEvent,
    StreamTextEvent,
    StreamToolCallEvent,
    get_model,
)
from inspect_ai.model._registry import modelapi
from inspect_ai.model._stream import (
    model_stream_requested,
    report_model_stream_delta,
    report_model_stream_progress,
    report_model_stream_restart,
    report_model_stream_start,
)
from inspect_ai.tool import ToolChoice, ToolDef, ToolInfo


class TransientError(Exception):
    pass


class ScriptedStreamAPI(ModelAPI):
    """Stub provider that runs one scripted coroutine per generate attempt."""

    # one entry per attempt; the last entry repeats
    script: list[Callable[["ScriptedStreamAPI"], Coroutine[Any, Any, ModelOutput]]] = []
    attempts: int = 0
    # pending events captured at the start of each attempt
    events: list[ModelEvent] = []

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: object,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key="scripted-api-key",
            api_key_vars=[],
            config=config,
        )

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, TransientError)

    def retry_wait(self) -> WaitBaseT:
        return tenacity.wait_fixed(0)

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        cls = type(self)
        attempt = cls.script[min(cls.attempts, len(cls.script) - 1)]
        cls.attempts += 1
        event = _active_model_event.get()
        assert isinstance(event, ModelEvent)
        cls.events.append(event)
        return await attempt(self)

    def _output(self, content: str = "final") -> ModelOutput:
        return ModelOutput.from_content(model=self.model_name, content=content)


async def _scripted_generate(
    script: list[Callable[[ScriptedStreamAPI], Coroutine[Any, Any, ModelOutput]]],
    on_stream: Any = None,
    config: GenerateConfig = GenerateConfig(),
    cache: bool = False,
) -> ModelOutput:
    """Run one generate against ScriptedStreamAPI with `script` installed."""

    @modelapi(name="mockstream")
    def mockstream() -> type[ModelAPI]:
        return ScriptedStreamAPI

    ScriptedStreamAPI.script = script
    ScriptedStreamAPI.attempts = 0
    ScriptedStreamAPI.events = []
    try:
        model = get_model("mockstream/test")
        return await model.generate(
            "hello", config=config, cache=cache, on_stream=on_stream
        )
    finally:
        del _registry["modelapi:mockstream"]


class Collector:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    async def __call__(self, event: StreamEvent) -> None:
        self.events.append(event)


async def test_on_stream_receives_deltas_and_final_output() -> None:
    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        report_model_stream_start()
        await report_model_stream_delta(StreamReasoningEvent(reasoning="hmm"))
        await report_model_stream_delta(StreamTextEvent(text="hel"))
        await report_model_stream_delta(StreamTextEvent(text="lo"))
        await report_model_stream_delta(
            StreamToolCallEvent(id="c1", function="bash", arguments='{"cmd"')
        )
        return api._output("hello")

    collector = Collector()
    output = await _scripted_generate([attempt], on_stream=collector)
    assert output.completion == "hello"
    assert [type(e) for e in collector.events] == [
        StreamReasoningEvent,
        StreamTextEvent,
        StreamTextEvent,
        StreamToolCallEvent,
    ]
    tool_event = collector.events[-1]
    assert isinstance(tool_event, StreamToolCallEvent)
    assert tool_event.id == "c1"
    assert tool_event.function == "bash"
    assert tool_event.arguments == '{"cmd"'


async def test_streaming_provider_works_without_on_stream() -> None:
    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        report_model_stream_start()
        await report_model_stream_delta(StreamTextEvent(text="hi"))
        return api._output("hi")

    output = await _scripted_generate([attempt])
    assert output.completion == "hi"


async def test_deltas_without_on_stream_are_heartbeat_only() -> None:
    """Deltas reported without `on_stream` feed only the progress heartbeat.

    A reported delta is on_stream support code with no consumer: no
    accumulation, no partial-output snapshot on the pending event.
    """

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        event = _active_model_event.get()
        assert isinstance(event, ModelEvent)
        await report_model_stream_delta(StreamTextEvent(text="unconsumed"))
        # heartbeat recorded, but no partial output was published
        progress = model_event_progress(event)
        assert progress is not None
        assert progress.last_progress_at is not None
        assert event.output.completion == ""
        return api._output("done")

    output = await _scripted_generate([attempt])
    assert output.completion == "done"


async def test_uninstrumented_provider_never_invokes_callback() -> None:
    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        return api._output("quiet")

    collector = Collector()
    output = await _scripted_generate([attempt], on_stream=collector)
    assert output.completion == "quiet"
    assert collector.events == []


async def test_retry_boundary_delivered_with_current_attempt_number() -> None:
    """Each retry after delivered deltas gets a boundary.

    Boundaries are emitted eagerly, so each carries the current attempt
    number even when the retried attempt itself streams no deltas before
    failing.
    """

    async def attempt_1(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="partial"))
        raise TransientError()

    async def attempt_2(api: ScriptedStreamAPI) -> ModelOutput:
        raise TransientError()  # fails before streaming anything

    async def attempt_3(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="done"))
        return api._output("done")

    collector = Collector()
    output = await _scripted_generate(
        [attempt_1, attempt_2, attempt_3],
        on_stream=collector,
        config=GenerateConfig(max_retries=3),
    )
    assert output.completion == "done"
    assert [type(e) for e in collector.events] == [
        StreamTextEvent,
        StreamRetryEvent,
        StreamRetryEvent,
        StreamTextEvent,
    ]
    assert [e.attempt for e in collector.events if isinstance(e, StreamRetryEvent)] == [
        2,
        3,
    ]


async def test_cache_hit_on_retry_still_delivers_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cache hit on a retry attempt must still deliver the retry boundary.

    A concurrent identical call can populate the cache between attempts;
    the cache-hit fast path runs no provider call, but the deltas already
    delivered belong to the failed attempt and must still be invalidated.
    """
    cached = ModelOutput.from_content(model="mockstream/test", content="cached")
    fetches = 0

    def fake_cache_fetch(entry: Any) -> ModelOutput | None:
        nonlocal fetches
        fetches += 1
        return cached if fetches > 1 else None

    monkeypatch.setattr("inspect_ai.model._model.cache_fetch", fake_cache_fetch)

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="partial"))
        raise TransientError()

    collector = Collector()
    output = await _scripted_generate(
        [attempt],
        on_stream=collector,
        config=GenerateConfig(max_retries=2),
        cache=True,
    )
    assert output.completion == "cached"
    assert ScriptedStreamAPI.attempts == 1  # attempt 2 was the cache hit
    assert [type(e) for e in collector.events] == [StreamTextEvent, StreamRetryEvent]
    boundary = collector.events[-1]
    assert isinstance(boundary, StreamRetryEvent)
    assert boundary.attempt == 2


async def test_provider_internal_restart_resets_output_and_reannounces() -> None:
    """A provider-internal retry replaces streamed output.

    report_model_stream_restart discards accumulated output — partial
    snapshot, token counters — and re-announces the current attempt to
    on_stream so consumers drop the replaced prefix.
    """

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        event = _active_model_event.get()
        assert isinstance(event, ModelEvent)
        report_model_stream_start()
        report_model_stream_progress(output_tokens=10)
        await report_model_stream_delta(StreamTextEvent(text="malformed"))
        assert event.output.completion == "malformed"

        await report_model_stream_restart()
        # partial snapshot discarded (with notification); the discarded
        # stream's token count is cleared rather than left to mislabel the
        # replacement response
        assert event.output.completion == ""
        progress = model_event_progress(event)
        assert progress is not None and progress.output_tokens is None

        report_model_stream_start()
        report_model_stream_progress(output_tokens=3)
        assert progress.output_tokens == 3
        await report_model_stream_delta(StreamTextEvent(text="good"))
        assert event.output.completion == "good"
        return api._output("good")

    collector = Collector()
    output = await _scripted_generate([attempt], on_stream=collector)
    assert output.completion == "good"
    assert [type(e) for e in collector.events] == [
        StreamTextEvent,
        StreamRetryEvent,
        StreamTextEvent,
    ]
    # a provider-internal retry re-announces the *current* attempt
    retry_event = collector.events[1]
    assert isinstance(retry_event, StreamRetryEvent)
    assert retry_event.attempt == 1


async def test_no_retry_boundary_without_prior_deltas() -> None:
    async def attempt_1(api: ScriptedStreamAPI) -> ModelOutput:
        raise TransientError()

    async def attempt_2(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="ok"))
        return api._output("ok")

    collector = Collector()
    output = await _scripted_generate(
        [attempt_1, attempt_2],
        on_stream=collector,
        config=GenerateConfig(max_retries=2),
    )
    assert output.completion == "ok"
    assert [type(e) for e in collector.events] == [StreamTextEvent]


async def test_partial_output_snapshot_on_pending_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("inspect_ai.model._stream.PARTIAL_OUTPUT_FLUSH_INTERVAL", 0.0)
    snapshots: list[tuple[bool | None, list[Any]]] = []

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        event = _active_model_event.get()
        assert isinstance(event, ModelEvent)
        await report_model_stream_delta(StreamReasoningEvent(reasoning="think"))
        await report_model_stream_delta(StreamTextEvent(text="hel"))
        await report_model_stream_delta(StreamTextEvent(text="lo"))
        content = event.output.message.content
        assert isinstance(content, list)
        snapshots.append((event.pending, list(content)))
        return api._output("hello")

    # partial snapshots are delta-driven, so they require an on_stream consumer
    output = await _scripted_generate([attempt], on_stream=Collector())
    assert output.completion == "hello"
    (pending, content) = snapshots[0]
    assert pending is True
    assert isinstance(content[0], ContentReasoning)
    assert content[0].reasoning == "think"
    # consecutive text deltas merge into a single content item
    assert isinstance(content[1], ContentText)
    assert content[1].text == "hello"
    # final output replaced the partial snapshot
    event = ScriptedStreamAPI.events[0]
    assert event.pending is None
    assert event.output.completion == "hello"


async def test_partial_output_flushes_are_throttled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Within-interval deltas must not notify transcript subscribers.

    Each notification is a realtime-buffer insert, so a defeated throttle
    re-creates the per-delta write cost the design forbids
    (design/ctl/generate-progress.md).
    """
    from inspect_ai.log._transcript import Transcript

    monkeypatch.setattr(
        "inspect_ai.model._stream.PARTIAL_OUTPUT_FLUSH_INTERVAL", 1000.0
    )
    calls = {"n": 0}
    orig_event_updated = Transcript._event_updated

    def counting_event_updated(self: Transcript, event: Any) -> None:
        calls["n"] += 1
        orig_event_updated(self, event)

    monkeypatch.setattr(Transcript, "_event_updated", counting_event_updated)

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        before = calls["n"]
        await report_model_stream_delta(StreamTextEvent(text="a"))
        # the first delta flushes immediately
        assert calls["n"] == before + 1
        await report_model_stream_delta(StreamTextEvent(text="b"))
        await report_model_stream_delta(StreamTextEvent(text="c"))
        # subsequent within-interval deltas do not notify
        assert calls["n"] == before + 1
        return api._output("abc")

    output = await _scripted_generate([attempt], on_stream=Collector())
    assert output.completion == "abc"


async def test_partial_output_discarded_when_attempt_fails() -> None:
    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="doomed"))
        # the partial snapshot was published before the failure
        event = _active_model_event.get()
        assert isinstance(event, ModelEvent)
        assert event.output.completion == "doomed"
        raise RuntimeError("boom")

    with pytest.raises(Exception):
        await _scripted_generate([attempt], on_stream=Collector())
    event = ScriptedStreamAPI.events[0]
    assert event.pending is None
    assert event.error is not None
    # the failed attempt's partial content must not survive on the event
    assert event.output.completion == ""


async def test_progress_record_heartbeat_and_tokens() -> None:
    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        event = _active_model_event.get()
        assert isinstance(event, ModelEvent)
        assert model_event_progress(event) is None
        report_model_stream_start()
        report_model_stream_progress()
        progress = model_event_progress(event)
        assert progress is not None
        assert progress.last_progress_at is not None
        # bare heartbeats never fabricate a token count
        assert progress.output_tokens is None
        report_model_stream_progress(output_tokens=7)
        assert progress.output_tokens == 7
        return api._output()

    await _scripted_generate([attempt])
    # progress record is not readable once the event completes
    assert model_event_progress(ScriptedStreamAPI.events[0]) is None


async def test_progress_tokens_accumulate_across_streams() -> None:
    """Re-opened streams add to prior streams' token totals.

    Cumulative counts from a re-opened stream (provider continuations, SDK
    stream restarts) add to prior streams' totals rather than overwriting.
    """

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        event = _active_model_event.get()
        assert isinstance(event, ModelEvent)
        report_model_stream_start()
        report_model_stream_progress(output_tokens=5)
        report_model_stream_start()
        report_model_stream_progress(output_tokens=3)
        progress = model_event_progress(event)
        assert progress is not None
        assert progress.output_tokens == 8
        return api._output()

    await _scripted_generate([attempt])


async def test_progress_record_resets_per_attempt() -> None:
    async def attempt_1(api: ScriptedStreamAPI) -> ModelOutput:
        report_model_stream_start()
        report_model_stream_progress(output_tokens=100)
        raise TransientError()

    async def attempt_2(api: ScriptedStreamAPI) -> ModelOutput:
        event = _active_model_event.get()
        assert isinstance(event, ModelEvent)
        report_model_stream_start()
        report_model_stream_progress(output_tokens=5)
        progress = model_event_progress(event)
        assert progress is not None
        # attempt 1's count died with its event; no carry-over
        assert progress.output_tokens == 5
        return api._output()

    await _scripted_generate(
        [attempt_1, attempt_2], config=GenerateConfig(max_retries=1)
    )
    # each attempt got its own pending event
    assert len(ScriptedStreamAPI.events) == 2
    assert ScriptedStreamAPI.events[0] is not ScriptedStreamAPI.events[1]


async def test_stream_reports_are_noops_outside_generate() -> None:
    # no observer installed: nothing raises, nothing recorded
    report_model_stream_start()
    report_model_stream_progress(output_tokens=5)
    await report_model_stream_delta(StreamTextEvent(text="nowhere"))


async def test_model_stream_requested_reflects_on_stream() -> None:
    """Providers consult this in their stream decision.

    Passing `on_stream` is itself sufficient to request streaming.
    """
    requested: list[bool] = []

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        requested.append(model_stream_requested())
        return api._output("done")

    await _scripted_generate([attempt], on_stream=Collector())
    await _scripted_generate([attempt])
    assert requested == [True, False]
    # and outside any generate call there is no observer at all
    assert model_stream_requested() is False


class EchoStreamAPI(ScriptedStreamAPI):
    """Streams each call's own input text, asserting per-call isolation."""

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        event = _active_model_event.get()
        assert isinstance(event, ModelEvent)
        text = input[0].text
        report_model_stream_start()
        await report_model_stream_delta(StreamTextEvent(text=text))
        # yield so the sibling generate interleaves mid-stream
        await anyio.sleep(0.01)
        report_model_stream_progress(output_tokens=len(text))
        await report_model_stream_delta(StreamTextEvent(text=text))
        # this call's pending event carries only this call's content/progress
        progress = model_event_progress(event)
        assert progress is not None and progress.output_tokens == len(text)
        assert event.output.completion == text
        return ModelOutput.from_content(model=self.model_name, content=text)


async def test_concurrent_generates_do_not_cross_talk() -> None:
    from inspect_ai._util._async import tg_collect

    @modelapi(name="mockstreamecho")
    def mockstreamecho() -> type[ModelAPI]:
        return EchoStreamAPI

    try:
        model = get_model("mockstreamecho/test")
        collector_a, collector_b = Collector(), Collector()
        await tg_collect(
            [
                lambda: model.generate("aaa", on_stream=collector_a),
                lambda: model.generate("bbb", on_stream=collector_b),
            ]
        )
        assert [
            e.text for e in collector_a.events if isinstance(e, StreamTextEvent)
        ] == ["aaa", "aaa"]
        assert [
            e.text for e in collector_b.events if isinstance(e, StreamTextEvent)
        ] == ["bbb", "bbb"]
        assert len(collector_a.events) == 2 and len(collector_b.events) == 2
    finally:
        del _registry["modelapi:mockstreamecho"]


class BrokenHandler:
    """Handler that always raises, counting how often it was invoked."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, event: StreamEvent) -> None:
        self.calls += 1
        raise ValueError("handler bug")


async def test_stream_handler_exception_logged_and_detached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising handler never fails the model call.

    It is logged once and detached for the remainder of the call
    (display-only contract). The logger call is asserted directly
    (not via caplog) because inspect's logging init — run by earlier
    tests in a full-suite run — stops propagation to caplog's handler.
    """

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="a"))
        await report_model_stream_delta(StreamTextEvent(text="b"))
        return api._output("done")

    import inspect_ai.model._stream as stream_module

    warnings: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        stream_module.logger, "warning", lambda *a, **k: warnings.append((a, k))
    )

    handler = BrokenHandler()
    output = await _scripted_generate([attempt], on_stream=handler)
    assert output.completion == "done"
    assert handler.calls == 1
    assert len(warnings) == 1
    assert "on_stream handler" in warnings[0][0][0]
    assert warnings[0][1].get("exc_info") is True


async def test_stream_handler_detach_persists_across_attempts() -> None:
    """Detach spans the whole generate call.

    A wrapper-level retry neither re-arms the handler nor delivers it a
    retry boundary.
    """

    async def attempt_1(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="a"))
        raise TransientError()

    async def attempt_2(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="b"))
        return api._output("done")

    handler = BrokenHandler()
    output = await _scripted_generate(
        [attempt_1, attempt_2],
        on_stream=handler,
        config=GenerateConfig(max_retries=2),
    )
    assert output.completion == "done"
    assert handler.calls == 1


async def test_stream_handler_rearms_on_next_generate_call() -> None:
    """Detach is scoped to one generate call: the next call tries again."""

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="x"))
        return api._output("ok")

    handler = BrokenHandler()
    await _scripted_generate([attempt], on_stream=handler)
    await _scripted_generate([attempt], on_stream=handler)
    assert handler.calls == 2


async def test_stream_handler_cancellation_propagates() -> None:
    """Only Exception is swallowed.

    Cancellation raised through the handler (e.g. a sample limit hit
    inside the await) must propagate.
    """

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="x"))
        return api._output()

    async def cancelling_handler(event: StreamEvent) -> None:
        raise FakeCancellation()

    with pytest.raises(FakeCancellation):
        await _scripted_generate([attempt], on_stream=cancelling_handler)


class FakeCancellation(BaseException):
    """Non-Exception BaseException, exercising the wrapper's cancellation path."""


async def test_partial_output_discard_on_cancellation_notifies_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation mid-stream must push the snapshot reset to live views.

    Unlike the error paths (where `complete()` notifies right after the
    discard), a cancelled event stays pending — without a notification from
    the discard itself, the realtime buffer's last-written row would keep
    the failed attempt's partial output until the sample finalizes.
    """
    from inspect_ai.log._transcript import Transcript

    snapshots: list[str] = []
    orig_event_updated = Transcript._event_updated

    def recording_event_updated(self: Transcript, event: Any) -> None:
        if isinstance(event, ModelEvent):
            snapshots.append(event.output.completion)
        orig_event_updated(self, event)

    monkeypatch.setattr(Transcript, "_event_updated", recording_event_updated)

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="doomed"))
        raise FakeCancellation()

    with pytest.raises(FakeCancellation):
        await _scripted_generate([attempt], on_stream=Collector())
    event = ScriptedStreamAPI.events[0]
    # finalization stays with the interrupt machinery — still pending
    assert event.pending is True
    assert event.output.completion == ""
    # the partial snapshot notified, then the discard notified its reset
    assert snapshots[-2:] == ["doomed", ""]


async def test_generate_loop_forwards_on_stream() -> None:
    @modelapi(name="mockstream")
    def mockstream() -> type[ModelAPI]:
        return ScriptedStreamAPI

    async def attempt(api: ScriptedStreamAPI) -> ModelOutput:
        await report_model_stream_delta(StreamTextEvent(text="streamed"))
        return api._output("no tools")

    ScriptedStreamAPI.script = [attempt]
    ScriptedStreamAPI.attempts = 0
    ScriptedStreamAPI.events = []
    collector = Collector()
    try:
        model = get_model("mockstream/test")
        messages, output = await model.generate_loop("hello", on_stream=collector)
    finally:
        del _registry["modelapi:mockstream"]
    assert output.completion == "no tools"
    assert [e.text for e in collector.events if isinstance(e, StreamTextEvent)] == [
        "streamed"
    ]


# live provider tests (--runapi): on_stream against real APIs. Passing
# on_stream must by itself enable streaming — no `streaming` model arg.


@skip_if_no_anthropic
async def test_anthropic_on_stream_live() -> None:
    collector = Collector()
    model = get_model("anthropic/claude-haiku-4-5")
    # max_tokens below the auto-streaming threshold (8192) and no thinking:
    # only the on_stream callback can be what turns streaming on
    output = await model.generate(
        "Reply with one short sentence about the sea.",
        config=GenerateConfig(max_tokens=1024),
        on_stream=collector,
    )
    streamed = "".join(
        e.text for e in collector.events if isinstance(e, StreamTextEvent)
    )
    assert streamed
    assert streamed == output.completion


@skip_if_no_anthropic
async def test_anthropic_on_stream_tool_call_live() -> None:
    async def add(x: int, y: int) -> int:
        return x + y

    collector = Collector()
    model = get_model("anthropic/claude-haiku-4-5")
    output = await model.generate(
        "Use the add tool to compute 5 + 3.",
        tools=[
            ToolDef(
                add,
                name="add",
                description="Add two numbers.",
                parameters={"x": "first number", "y": "second number"},
            )
        ],
        config=GenerateConfig(max_tokens=1024),
        on_stream=collector,
    )
    assert output.message.tool_calls
    tool_events = [e for e in collector.events if isinstance(e, StreamToolCallEvent)]
    assert any(e.function == "add" for e in tool_events)
    arguments = json.loads("".join(e.arguments for e in tool_events))
    assert arguments == {"x": 5, "y": 3}


@skip_if_no_google
async def test_google_on_stream_live() -> None:
    collector = Collector()
    model = get_model("google/gemini-3.1-flash-lite")
    output = await model.generate(
        "Reply with one short sentence about the sea.", on_stream=collector
    )
    streamed = "".join(
        e.text for e in collector.events if isinstance(e, StreamTextEvent)
    )
    assert streamed
    assert streamed == output.completion


@skip_if_no_openai
async def test_openai_on_stream_live() -> None:
    collector = Collector()
    # gpt-4o family defaults to the chat-completions API
    model = get_model("openai/gpt-4o-mini")
    output = await model.generate(
        "Reply with one short sentence about the sea.", on_stream=collector
    )
    streamed = "".join(
        e.text for e in collector.events if isinstance(e, StreamTextEvent)
    )
    assert streamed
    assert streamed == output.completion


@skip_if_no_openai
async def test_openai_on_stream_tool_call_live() -> None:
    # inspect never sets `strict` on tools, so this exercises streaming a
    # non-strict tool request live (the SDK's .stream() helper would reject
    # it client-side; the raw create(stream=True) path must accept it)
    async def add(x: int, y: int) -> int:
        return x + y

    collector = Collector()
    model = get_model("openai/gpt-4o-mini")
    output = await model.generate(
        "Use the add tool to compute 5 + 3.",
        tools=[
            ToolDef(
                add,
                name="add",
                description="Add two numbers.",
                parameters={"x": "first number", "y": "second number"},
            )
        ],
        on_stream=collector,
    )
    assert output.message.tool_calls
    tool_events = [e for e in collector.events if isinstance(e, StreamToolCallEvent)]
    assert any(e.function == "add" for e in tool_events)
    arguments = json.loads("".join(e.arguments for e in tool_events))
    assert arguments == {"x": 5, "y": 3}


@skip_if_no_openai
async def test_openai_responses_on_stream_live() -> None:
    collector = Collector()
    # gpt-5 family defaults to the Responses API
    model = get_model("openai/gpt-5-mini")
    output = await model.generate(
        "Reply with one short sentence about the sea.", on_stream=collector
    )
    streamed = "".join(
        e.text for e in collector.events if isinstance(e, StreamTextEvent)
    )
    assert streamed
    assert streamed == output.completion


@skip_if_no_grok
async def test_grok_on_stream_live() -> None:
    collector = Collector()
    model = get_model("grok/grok-3-mini")
    output = await model.generate(
        "Reply with one short sentence about the sea.", on_stream=collector
    )
    streamed = "".join(
        e.text for e in collector.events if isinstance(e, StreamTextEvent)
    )
    assert streamed
    assert streamed == output.completion
