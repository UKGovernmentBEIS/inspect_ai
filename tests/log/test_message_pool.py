"""Tests for message pool deduplication in .eval files."""

import json
import os
import tempfile
from typing import Literal

import pytest
from pydantic import JsonValue

from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._condense import (
    condense_events,
    condense_sample,
    expand_events,
    resolve_sample_attachments,
)
from inspect_ai.log._file import read_eval_log, write_eval_log
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSpec,
    EvalStats,
)
from inspect_ai.log._pool import (
    _compress_refs,
    _expand_refs,
    resolve_sample_events_data,
)
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput


@pytest.fixture(autouse=True)
def _enable_v3_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pool tests require v3 format to be enabled."""
    monkeypatch.setenv("INSPECT_LOG_CONDENSE", "1")


def _make_sample_with_repeated_inputs() -> EvalSample:
    """Create a sample where model events have overlapping input messages."""
    msg_sys = ChatMessageSystem(content="You are helpful.")
    msg_user = ChatMessageUser(content="What is 2+2?")
    msg_asst = ChatMessageAssistant(content="4")
    msg_user2 = ChatMessageUser(content="And 3+3?")
    msg_asst2 = ChatMessageAssistant(content="6")

    event1 = ModelEvent(
        model="test-model",
        input=[msg_sys, msg_user],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
    )
    event2 = ModelEvent(
        model="test-model",
        input=[msg_sys, msg_user, msg_asst, msg_user2],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
    )
    event3 = ModelEvent(
        model="test-model",
        input=[msg_sys, msg_user, msg_asst, msg_user2, msg_asst2],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
    )

    return EvalSample(
        id="test",
        epoch=1,
        input="test",
        target="test",
        messages=[msg_sys, msg_user, msg_asst, msg_user2, msg_asst2],
        events=[event1, event2, event3],
    )


def test_condense_builds_message_pool():
    """condense_sample should extract messages into events_data."""
    sample = _make_sample_with_repeated_inputs()
    condensed = condense_sample(sample)

    # events_data should contain all unique messages
    assert condensed.events_data is not None
    assert len(condensed.events_data["messages"]) > 0

    # Each model event should have input_refs
    model_events = [e for e in condensed.events if isinstance(e, ModelEvent)]
    for event in model_events:
        assert event.input_refs is not None
        assert len(event.input) == 0


def test_condense_message_pool_no_duplication():
    """Messages appearing in multiple events should be stored once."""
    sample = _make_sample_with_repeated_inputs()
    condensed = condense_sample(sample)

    # 5 unique messages across 3 events
    assert condensed.events_data is not None
    assert len(condensed.events_data["messages"]) == 5

    # Verify dedup by resolving: events should have 2 + 4 + 5 = 11 total messages
    resolved = resolve_sample_events_data(condensed)
    model_events = [e for e in resolved.events if isinstance(e, ModelEvent)]
    total_msgs = sum(len(e.input) for e in model_events)
    assert total_msgs == 11


def test_resolve_reconstructs_model_event_inputs():
    """resolve_sample_attachments should rebuild input from input_refs + message_pool."""
    sample = _make_sample_with_repeated_inputs()
    condensed = condense_sample(sample)

    # Resolve
    resolved = resolve_sample_attachments(condensed, "full")

    # Model events should have full input restored
    model_events = [e for e in resolved.events if isinstance(e, ModelEvent)]
    assert len(model_events[0].input) == 2
    assert len(model_events[1].input) == 4
    assert len(model_events[2].input) == 5

    # input_refs should be cleared
    for event in model_events:
        assert event.input_refs is None

    # events_data should be cleared
    assert resolved.events_data is None


def test_condense_resolve_round_trip():
    """Condense then resolve should preserve message content."""
    sample = _make_sample_with_repeated_inputs()
    condensed = condense_sample(sample)
    resolved = resolve_sample_attachments(condensed, "full")

    original_model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    resolved_model_events = [e for e in resolved.events if isinstance(e, ModelEvent)]

    for orig, res in zip(original_model_events, resolved_model_events):
        assert len(orig.input) == len(res.input)
        for orig_msg, res_msg in zip(orig.input, res.input):
            assert orig_msg.role == res_msg.role
            # Content may have been through attachment condensation (strings > 100 chars),
            # but our short test messages should survive unchanged
            assert orig_msg.content == res_msg.content


def test_read_v2_eval_file():
    """Reading a v2 .eval file should work -- empty message_pool, input populated."""
    log_file = os.path.join("tests", "log", "test_eval_log", "log_read_sample.eval")
    if not os.path.exists(log_file):
        pytest.skip("Test fixture not available")

    log = read_eval_log(log_file)
    # v2 file should still read; version stays as written in the file
    assert log.version >= 2
    if log.samples:
        sample = log.samples[0]
        assert sample.events_data is None
        model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
        for event in model_events:
            assert event.input_refs is None


def _make_eval_log_with_model_events() -> EvalLog:
    """Create a minimal EvalLog with model events that have repeated inputs.

    The samples are pre-condensed (condense_sample called) since write_eval_log
    does not call condense_sample itself -- that happens at eval run time.
    """
    sample = _make_sample_with_repeated_inputs()
    condensed_sample = condense_sample(sample)
    return EvalLog(
        version=LOG_SCHEMA_VERSION,
        status="success",
        eval=EvalSpec(
            task="test_task",
            task_version=0,
            task_id="test",
            model="test-model",
            dataset=EvalDataset(name="test", samples=1),
            config=EvalConfig(),
            created="2025-01-01T00:00:00Z",
        ),
        plan=EvalPlan(),
        results=EvalResults(total_samples=1, completed_samples=1),
        stats=EvalStats(
            started_at="2025-01-01T00:00:00Z",
            completed_at="2025-01-01T00:01:00Z",
        ),
        samples=[condensed_sample],
    )


@pytest.mark.parametrize(
    "resolve_attachments",
    [
        pytest.param(None, id="default"),
        pytest.param("full", id="resolve-full"),
        pytest.param(False, id="no-resolve"),
    ],
)
def test_write_read_round_trip(
    resolve_attachments: Literal["full", "core"] | bool | None,
):
    """Write a v3 .eval file and read it back -- message pool is always resolved."""
    log = _make_eval_log_with_model_events()

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.eval")
        write_eval_log(log, path)

        if resolve_attachments is not None:
            read_log = read_eval_log(path, resolve_attachments=resolve_attachments)
        else:
            read_log = read_eval_log(path)
        assert read_log.version == 2
        assert read_log.samples is not None
        assert len(read_log.samples) == 1

        sample = read_log.samples[0]
        assert sample.events_data is None  # resolved

        model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
        assert len(model_events[0].input) == 2
        assert len(model_events[1].input) == 4
        assert len(model_events[2].input) == 5
        for event in model_events:
            assert event.input_refs is None


def test_write_eval_log_applies_condensing():
    """write_eval_log should apply condense_sample even when given uncondensed samples."""
    sample = _make_sample_with_repeated_inputs()
    # Verify sample is NOT pre-condensed
    assert sample.events_data is None

    log = EvalLog(
        version=LOG_SCHEMA_VERSION,
        status="success",
        eval=EvalSpec(
            task="test_task",
            task_version=0,
            task_id="test",
            model="test-model",
            dataset=EvalDataset(name="test", samples=1),
            config=EvalConfig(),
            created="2025-01-01T00:00:00Z",
        ),
        plan=EvalPlan(),
        results=EvalResults(total_samples=1, completed_samples=1),
        stats=EvalStats(
            started_at="2025-01-01T00:00:00Z",
            completed_at="2025-01-01T00:01:00Z",
        ),
        samples=[sample],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.eval")
        write_eval_log(log, path)

        # Read raw zip to verify condensing was applied at write time
        import zipfile

        with zipfile.ZipFile(path) as zf:
            sample_files = [n for n in zf.namelist() if n.startswith("samples/")]
            assert len(sample_files) == 1
            raw = json.loads(zf.read(sample_files[0]))
            # events_data should be populated (condensing was applied)
            assert raw.get("events_data") is not None
            assert len(raw["events_data"]["messages"]) > 0


def test_condense_anonymous_message_ids():
    """Messages without IDs should still be deduplicated into the pool."""
    msg1 = ChatMessageUser(content="Hello")
    msg1.id = None  # explicitly no ID
    msg2 = ChatMessageAssistant(content="Hi")
    msg2.id = None

    event = ModelEvent(
        model="test-model",
        input=[msg1, msg2],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
    )
    sample = EvalSample(id="test", epoch=1, input="test", target="test", events=[event])
    condensed = condense_sample(sample)

    assert condensed.events_data is not None
    assert len(condensed.events_data["messages"]) == 2


def _make_sample_with_call_messages() -> EvalSample:
    """Create a sample where model events have call.request.messages with overlap."""
    msg1: dict[str, JsonValue] = {"role": "user", "content": "Hello"}
    msg2: dict[str, JsonValue] = {"role": "assistant", "content": "Hi"}
    msg3: dict[str, JsonValue] = {"role": "user", "content": "How are you?"}

    call1 = ModelCall(
        request={"model": "test", "messages": [msg1]},
        response={"choices": []},
    )
    call2 = ModelCall(
        request={"model": "test", "messages": [msg1, msg2, msg3]},
        response={"choices": []},
    )

    event1 = ModelEvent(
        model="test-model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
        call=call1,
    )
    event2 = ModelEvent(
        model="test-model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
        call=call2,
    )

    return EvalSample(
        id="test",
        epoch=1,
        input="test",
        target="test",
        events=[event1, event2],
    )


def test_condense_call_request_messages():
    """condense_sample should extract call.request.messages into call_pool."""
    sample = _make_sample_with_call_messages()
    condensed = condense_sample(sample)

    assert condensed.events_data is not None
    assert len(condensed.events_data["calls"]) == 3

    model_events = [e for e in condensed.events if isinstance(e, ModelEvent)]
    for event in model_events:
        assert event.call is not None
        assert event.call.call_refs is not None
        assert "messages" not in event.call.request
        assert event.call.call_key == "messages"

    # Event 1: 1 message -> [(0,1)]
    assert model_events[0].call.call_refs == [(0, 1)]
    # Event 2: 3 messages -> [(0,3)]
    assert model_events[1].call.call_refs == [(0, 3)]


def test_resolve_call_request_messages():
    """Resolving should restore call.request.messages from refs."""
    sample = _make_sample_with_call_messages()
    condensed = condense_sample(sample)
    resolved = resolve_sample_attachments(condensed, "full")

    model_events = [e for e in resolved.events if isinstance(e, ModelEvent)]
    assert len(model_events[0].call.request["messages"]) == 1
    assert len(model_events[1].call.request["messages"]) == 3
    assert model_events[0].call.call_refs is None
    assert model_events[1].call.call_refs is None
    assert resolved.events_data is None


def test_call_pool_round_trip_content_preserved():
    """Condense then resolve should preserve message content exactly."""
    sample = _make_sample_with_call_messages()
    orig_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    orig_msgs = [e.call.request["messages"] for e in orig_events]

    condensed = condense_sample(sample)
    resolved = resolve_sample_attachments(condensed, "full")

    resolved_events = [e for e in resolved.events if isinstance(e, ModelEvent)]
    for orig, res in zip(orig_msgs, resolved_events):
        assert orig == res.call.request["messages"]


def test_condense_call_no_messages_key():
    """If call.request has no messages key, it should be left unchanged."""
    call = ModelCall(
        request={"model": "test", "prompt": "hello"},
        response={"choices": []},
    )
    event = ModelEvent(
        model="test-model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
        call=call,
    )
    sample = EvalSample(
        id="test",
        epoch=1,
        input="test",
        target="test",
        events=[event],
    )
    condensed = condense_sample(sample)

    assert condensed.events_data is None or not condensed.events_data["calls"]
    model_events = [e for e in condensed.events if isinstance(e, ModelEvent)]
    assert model_events[0].call.call_refs is None
    assert model_events[0].call.request["prompt"] == "hello"


def test_condense_call_request_contents_key():
    """condense_sample should handle call.request.contents (not just messages)."""
    msg1 = {"role": "user", "content": "Hello via contents"}
    msg2 = {"role": "assistant", "content": "Reply"}

    call = ModelCall(
        request={"model": "test", "contents": [msg1, msg2]},
        response={"choices": []},
    )
    event = ModelEvent(
        model="test-model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
        call=call,
    )
    sample = EvalSample(
        id="test",
        epoch=1,
        input="test",
        target="test",
        events=[event],
    )
    condensed = condense_sample(sample)

    # Should extract into events_data calls with call_key="contents"
    assert condensed.events_data is not None
    assert len(condensed.events_data["calls"]) == 2
    model_events = [e for e in condensed.events if isinstance(e, ModelEvent)]
    assert model_events[0].call.call_key == "contents"
    assert model_events[0].call.call_refs is not None
    assert "contents" not in model_events[0].call.request

    # Resolve should restore under "contents" key
    resolved = resolve_sample_attachments(condensed, "full")
    resolved_events = [e for e in resolved.events if isinstance(e, ModelEvent)]
    assert resolved_events[0].call.request["contents"] == [msg1, msg2]
    assert resolved_events[0].call.call_refs is None
    assert resolved.events_data is None


def test_write_read_round_trip_call_pool():
    """Write a .eval file with call_pool and read it back."""
    sample = _make_sample_with_call_messages()
    condensed = condense_sample(sample)
    log = EvalLog(
        version=LOG_SCHEMA_VERSION,
        status="success",
        eval=EvalSpec(
            task="test_task",
            task_version=0,
            task_id="test",
            model="test-model",
            dataset=EvalDataset(name="test", samples=1),
            config=EvalConfig(),
            created="2025-01-01T00:00:00Z",
        ),
        plan=EvalPlan(),
        results=EvalResults(total_samples=1, completed_samples=1),
        stats=EvalStats(
            started_at="2025-01-01T00:00:00Z",
            completed_at="2025-01-01T00:01:00Z",
        ),
        samples=[condensed],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.eval")
        write_eval_log(log, path)

        read_log = read_eval_log(path, resolve_attachments="full")
        assert read_log.samples is not None
        sample = read_log.samples[0]

        # events_data resolved
        assert sample.events_data is None

        # call.request.messages restored
        model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
        assert len(model_events[0].call.request["messages"]) == 1
        assert len(model_events[1].call.request["messages"]) == 3
        assert model_events[0].call.call_refs is None


def test_read_sample_exclude_fields_preserves_events_data():
    """Excluding events_data should be silently ignored (needed for resolution)."""
    sample = _make_sample_with_call_messages()
    condensed = condense_sample(sample)
    log = _make_eval_log_with_model_events()
    # Replace sample with one that has events_data
    log.samples = [condensed]

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.eval")
        write_eval_log(log, path)

        from inspect_ai.log._file import read_eval_log_sample

        sample = read_eval_log_sample(path, id="test", exclude_fields={"events_data"})
        # events_data should have been resolved despite exclude_fields
        assert sample.events_data is None
        model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
        assert len(model_events[0].call.request["messages"]) == 1
        assert len(model_events[1].call.request["messages"]) == 3


def test_condense_is_idempotent():
    """Calling condense_sample twice should produce the same result."""
    sample = _make_sample_with_repeated_inputs()
    condensed_once = condense_sample(sample)
    condensed_twice = condense_sample(condensed_once)

    # Pools should be identical
    assert condensed_once.events_data is not None
    assert condensed_twice.events_data is not None
    assert len(condensed_twice.events_data["messages"]) == len(
        condensed_once.events_data["messages"]
    )
    assert len(condensed_twice.events_data["calls"]) == len(
        condensed_once.events_data["calls"]
    )

    # Events should still have refs
    model_events = [e for e in condensed_twice.events if isinstance(e, ModelEvent)]
    for event in model_events:
        assert event.input_refs is not None
        assert len(event.input) == 0


def test_condense_is_idempotent_call_pool():
    """Calling condense_sample twice should preserve call_pool."""
    sample = _make_sample_with_call_messages()
    condensed_once = condense_sample(sample)
    condensed_twice = condense_sample(condensed_once)

    assert condensed_once.events_data is not None
    assert condensed_twice.events_data is not None
    assert len(condensed_twice.events_data["calls"]) == len(
        condensed_once.events_data["calls"]
    )

    model_events = [e for e in condensed_twice.events if isinstance(e, ModelEvent)]
    for event in model_events:
        if event.call and event.call.call_refs is not None:
            assert len(event.call.call_refs) > 0


def test_stream_convert_preserves_message_pool():
    """Streaming conversion of a v3 file should preserve message pool data."""
    from inspect_ai.log._convert import convert_eval_logs

    log = _make_eval_log_with_model_events()

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.eval")
        output_dir = os.path.join(tmpdir, "output")
        os.makedirs(output_dir)
        write_eval_log(log, input_path)

        # Convert with streaming (stream=2)
        convert_eval_logs(input_path, "eval", output_dir, stream=2)

        output_path = os.path.join(output_dir, "input.eval")
        read_log = read_eval_log(output_path)
        assert read_log.samples is not None
        sample = read_log.samples[0]

        # Model events should have full input restored
        model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
        assert len(model_events[0].input) == 2
        assert len(model_events[1].input) == 4
        assert len(model_events[2].input) == 5


@pytest.mark.parametrize(
    "indices, expected",
    [
        pytest.param([0, 1, 2, 3, 4], [(0, 5)], id="contiguous-prefix"),
        pytest.param([3, 4, 5], [(3, 6)], id="contiguous-with-offset"),
        pytest.param([0, 1, 2, 7, 8, 9], [(0, 3), (7, 10)], id="two-ranges"),
        pytest.param(
            [0, 3, 4, 5, 9], [(0, 1), (3, 6), (9, 10)], id="mixed-singles-and-ranges"
        ),
        pytest.param([2, 5, 8], [(2, 3), (5, 6), (8, 9)], id="all-singles"),
        pytest.param([7], [(7, 8)], id="single-element"),
        pytest.param([], [], id="empty"),
        pytest.param([3, 4], [(3, 5)], id="pair"),
        pytest.param([1, 2, 0], [(1, 3), (0, 1)], id="non-increasing"),
        pytest.param([1, 1, 0], [(1, 2), (1, 2), (0, 1)], id="repeated"),
    ],
)
def test_compress_refs(indices: list[int], expected: list[tuple[int, int]]):
    assert _compress_refs(indices) == expected


@pytest.mark.parametrize(
    "refs, pool, expected",
    [
        pytest.param([(0, 5)], list(range(10)), [0, 1, 2, 3, 4], id="range"),
        pytest.param(
            [(2, 3), (5, 6), (8, 9)],
            [f"msg{i}" for i in range(10)],
            ["msg2", "msg5", "msg8"],
            id="singles",
        ),
        pytest.param(
            [(0, 1), (3, 6), (9, 10)], list(range(10)), [0, 3, 4, 5, 9], id="mixed"
        ),
    ],
)
def test_expand_refs(
    refs: list[tuple[int, int]], pool: list[object], expected: list[object]
):
    assert _expand_refs(refs, pool) == expected


def test_compress_expand_round_trip():
    """Compress then expand should recover original indices."""
    pool = list(range(20))
    indices = [0, 1, 2, 3, 10, 11, 12, 15]
    compressed = _compress_refs(indices)
    assert _expand_refs(compressed, pool) == [pool[i] for i in indices]


def test_condense_produces_range_encoded_input_refs():
    """Standard agentic inputs should produce range-encoded refs."""
    sample = _make_sample_with_repeated_inputs()
    condensed = condense_sample(sample)
    model_events = [e for e in condensed.events if isinstance(e, ModelEvent)]
    # Turn 1: 2 messages [0,1] -> [(0,2)]
    assert model_events[0].input_refs == [(0, 2)]
    # Turn 2: 4 messages [0,1,2,3] -> [(0,4)]
    assert model_events[1].input_refs == [(0, 4)]
    # Turn 3: 5 messages [0,1,2,3,4] -> [(0,5)]
    assert model_events[2].input_refs == [(0, 5)]


def test_condense_produces_range_encoded_call_refs():
    """Standard call refs should produce range encoding."""
    sample = _make_sample_with_call_messages()
    condensed = condense_sample(sample)
    model_events = [e for e in condensed.events if isinstance(e, ModelEvent)]
    # Event 1: 1 message [0] -> [(0,1)]
    assert model_events[0].call.call_refs == [(0, 1)]
    # Event 2: 3 messages [0,1,2] -> [(0,3)]
    assert model_events[1].call.call_refs == [(0, 3)]


def test_resolve_range_encoded_input_refs():
    """Resolver should expand range-encoded input_refs from list pool."""
    msg1 = ChatMessageSystem(content="System")
    msg2 = ChatMessageUser(content="Hello")
    msg3 = ChatMessageAssistant(content="Hi")
    sample = EvalSample(
        id="test",
        epoch=1,
        input="test",
        target="test",
        events_data={"messages": [msg1, msg2, msg3], "calls": []},
        events=[
            ModelEvent(
                model="test-model",
                input=[],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput(),
                input_refs=[(0, 3)],
            )
        ],
    )
    resolved = resolve_sample_events_data(sample)
    model_events = [e for e in resolved.events if isinstance(e, ModelEvent)]
    assert len(model_events[0].input) == 3
    assert model_events[0].input[0].content == "System"
    assert model_events[0].input[2].content == "Hi"
    assert model_events[0].input_refs is None


def test_resolve_range_encoded_call_refs():
    """Resolver should expand range-encoded call_refs from list pool."""
    m1 = {"role": "user", "content": "Hello"}
    m2 = {"role": "assistant", "content": "Hi"}
    call = ModelCall(
        request={"model": "test"},
        response=None,
        call_refs=[(0, 2)],
        call_key="messages",
    )
    sample = EvalSample(
        id="test",
        epoch=1,
        input="test",
        target="test",
        events_data={"messages": [], "calls": [m1, m2]},
        events=[
            ModelEvent(
                model="test-model",
                input=[],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput(),
                call=call,
            )
        ],
    )
    resolved = resolve_sample_events_data(sample)
    model_events = [e for e in resolved.events if isinstance(e, ModelEvent)]
    assert model_events[0].call.request["messages"] == [m1, m2]
    assert model_events[0].call.call_refs is None


def test_condense_same_id_different_content_gets_separate_pool_entries():
    """Messages with the same .id but different content must get separate pool entries.

    This tests hash-based dedup: even though msg.id is identical, the different
    content produces different hashes, so both versions are stored separately.
    """
    shared_id = "same-id-for-both"
    user_msg = ChatMessageUser(content="Hello")
    assistant_msg = ChatMessageAssistant(
        id=shared_id,
        content=[ContentText(text="Answer"), ContentReasoning(reasoning="thinking...")],
    )

    # Same ID, different content (user mutated without updating ID)
    stripped_msg = ChatMessageAssistant(
        id=shared_id,
        content=[ContentText(text="Answer")],
    )

    event1 = ModelEvent(
        model="test",
        input=[user_msg, assistant_msg],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(model="test"),
    )
    event2 = ModelEvent(
        model="test",
        input=[user_msg, stripped_msg],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(model="test"),
    )

    sample = EvalSample(
        id=1,
        epoch=1,
        input="test",
        target="test",
        events=[event1, event2],
    )

    condensed = condense_sample(sample)

    # user_msg + two different assistant versions = 3 pool entries
    assert condensed.events_data is not None
    assert len(condensed.events_data["messages"]) == 3

    # Round-trip: resolve and verify content is preserved
    resolved = resolve_sample_events_data(condensed)
    resolved_event1_input = resolved.events[0].input
    resolved_event2_input = resolved.events[1].input

    # Event 1 should have reasoning, event 2 should not
    assert any(
        isinstance(c, ContentReasoning)
        for msg in resolved_event1_input
        if isinstance(msg.content, list)
        for c in msg.content
    )
    assert not any(
        isinstance(c, ContentReasoning)
        for msg in resolved_event2_input
        if isinstance(msg.content, list)
        for c in msg.content
    )


def test_resolve_shares_message_instances():
    """Resolved events share the same ChatMessage objects — no N² duplication."""
    sample = _make_sample_with_repeated_inputs()
    condensed = condense_sample(sample)
    resolved = resolve_sample_events_data(condensed)

    model_events = [e for e in resolved.events if isinstance(e, ModelEvent)]
    # Events 0, 1, 2 all start with the same system + user prefix
    assert model_events[0].input[0] is model_events[1].input[0]
    assert model_events[0].input[0] is model_events[2].input[0]
    assert model_events[0].input[1] is model_events[1].input[1]
    assert model_events[1].input[2] is model_events[2].input[2]
    assert model_events[1].input[3] is model_events[2].input[3]


def test_condense_expand_events_round_trip():
    """condense_events + expand_events should preserve message content."""
    sample = _make_sample_with_repeated_inputs()
    condensed, data = condense_events(sample.events)

    assert len(data["messages"]) == 5
    assert isinstance(data["calls"], list)

    expanded = expand_events(condensed, data)
    model_events = [e for e in expanded if isinstance(e, ModelEvent)]
    assert len(model_events[0].input) == 2
    assert len(model_events[1].input) == 4
    assert len(model_events[2].input) == 5


def test_condense_expand_events_call_pool_round_trip():
    """condense_events + expand_events round-trips call pools."""
    sample = _make_sample_with_call_messages()
    condensed, data = condense_events(sample.events)

    assert len(data["calls"]) == 3

    expanded = expand_events(condensed, data)
    model_events = [e for e in expanded if isinstance(e, ModelEvent)]
    assert len(model_events[0].call.request["messages"]) == 1
    assert len(model_events[1].call.request["messages"]) == 3


def test_expand_events_json_string_events():
    """expand_events accepts events as a JSON string."""
    sample = _make_sample_with_repeated_inputs()
    condensed, data = condense_events(sample.events)
    events_json = json.dumps([e.model_dump() for e in condensed])

    expanded = expand_events(events_json, data)
    model_events = [e for e in expanded if isinstance(e, ModelEvent)]
    assert len(model_events[0].input) == 2
    assert len(model_events[1].input) == 4
    assert len(model_events[2].input) == 5


def test_expand_events_json_string_data():
    """expand_events accepts data as a JSON string."""
    sample = _make_sample_with_repeated_inputs()
    condensed, data = condense_events(sample.events)
    data_json = json.dumps(
        {
            "messages": [m.model_dump() for m in data["messages"]],
            "calls": data["calls"],
        }
    )

    expanded = expand_events(condensed, data_json)
    model_events = [e for e in expanded if isinstance(e, ModelEvent)]
    assert len(model_events[0].input) == 2
    assert len(model_events[1].input) == 4
    assert len(model_events[2].input) == 5


def test_expand_events_both_json_strings():
    """expand_events accepts both params as JSON strings."""
    sample = _make_sample_with_call_messages()
    condensed, data = condense_events(sample.events)
    events_json = json.dumps([e.model_dump() for e in condensed])
    data_json = json.dumps(
        {
            "messages": [m.model_dump() for m in data["messages"]],
            "calls": data["calls"],
        }
    )

    expanded = expand_events(events_json, data_json)
    model_events = [e for e in expanded if isinstance(e, ModelEvent)]
    assert len(model_events[0].call.request["messages"]) == 1
    assert len(model_events[1].call.request["messages"]) == 3


def test_expand_events_empty_pools_is_noop():
    """expand_events with empty pools returns events unchanged."""
    sample = _make_sample_with_repeated_inputs()
    result = expand_events(sample.events, {"messages": [], "calls": []})
    assert len(result) == len(sample.events)


def test_resolve_call_empty_refs_preserves_request():
    """Resolve must not corrupt call.request when call_refs is [] (deserialized as empty).

    Regression: if persistence stores call_refs as [] instead of null,
    resolve_model_event_calls fires ([] is not None), expands to no messages,
    then sets request[default_key] = [], adding a spurious 'messages' key
    and potentially masking the original 'input' field.
    """
    from inspect_ai.log._pool import resolve_model_event_calls

    call = ModelCall(
        request={"model": "test", "input": "What is 2+2?"},
        response={"choices": []},
        call_refs=[],  # simulates deserialization storing [] instead of null
        call_key=None,
    )
    event = ModelEvent(
        model="test-model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
        call=call,
    )

    resolved = resolve_model_event_calls([event], call_pool=["dummy"])
    resolved_call = resolved[0].call

    # request must be unchanged — no spurious keys, 'input' preserved
    assert resolved_call.request == {"model": "test", "input": "What is 2+2?"}
    assert "messages" not in resolved_call.request
