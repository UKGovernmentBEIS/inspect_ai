"""End-to-end test: DB condensation → filestore flush → read → verify pool refs.

This test simulates the full streaming pipeline:
1. Events are condensed and stored in a SampleBufferDatabase
2. Data is flushed to a SampleBufferFilestore (local filesystem, not S3)
3. Data is read from the filestore (simulating the viewer's API call)
4. Pool refs are expanded and verified against expected messages
"""

import json
import tempfile
from pathlib import Path
from typing import Any, Generator

import pytest

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer.database import (
    SampleBufferDatabase,
    sync_to_filestore,
)
from inspect_ai.log._recorders.buffer.filestore import SampleBufferFilestore
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput


@pytest.fixture
def workspace() -> Generator[
    tuple[SampleBufferDatabase, SampleBufferFilestore], None, None
]:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_dir = Path(tmpdir) / "db"
        fs_dir = Path(tmpdir) / "fs"
        db_dir.mkdir()
        fs_dir.mkdir()

        location = str(fs_dir / "test.eval")
        db = SampleBufferDatabase(
            location=location,
            db_dir=db_dir,
            log_shared=None,
        )
        filestore = SampleBufferFilestore(location, create=True)
        yield db, filestore
        db.cleanup()
        filestore.cleanup()


def _make_event(input_msgs: list, call_msgs: Any = None) -> ModelEvent:
    call = (
        ModelCall(request={"messages": call_msgs}, response={})
        if call_msgs is not None
        else None
    )
    return ModelEvent(
        model="test-model",
        input=input_msgs,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
        call=call,
    )


def _expand_refs(refs: Any, pool: list) -> list:
    assert isinstance(refs, list)
    result = []
    for start, end in refs:
        result.extend(pool[start:end])
    return result


def test_full_pipeline_pool_refs_correct(
    workspace: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Verify pool refs resolve correctly through the full DB → filestore pipeline."""
    db, filestore = workspace
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    sys_msg = ChatMessageSystem(content="You are a helpful assistant.")
    scenario = ChatMessageUser(content="Scenario: decision theory problem")
    user1 = ChatMessageUser(content="What should I do?")
    asst1 = ChatMessageAssistant(content="I think you should cooperate.")
    tool1 = ChatMessageTool(content="Tool result: verified", tool_call_id="tc1")
    user2 = ChatMessageUser(content="Are you sure?")
    asst2 = ChatMessageAssistant(content="Yes, I'm confident.")
    user3 = ChatMessageUser(content="OK, let's proceed.")

    expected_per_turn = [
        [sys_msg, scenario, user1],
        [sys_msg, scenario, user1, asst1, tool1, user2],
        [sys_msg, scenario, user1, asst1, tool1, user2, asst2, user3],
    ]

    # Log events one at a time (simulating streaming)
    for msgs in expected_per_turn:
        db.log_events([SampleEvent(id="s1", epoch=1, event=_make_event(msgs))])

    # Flush to filestore
    sync_to_filestore(db, filestore)

    # Read from filestore (simulating viewer's first poll, no cursors)
    fs_data = filestore.get_sample_data("s1", 1)
    assert fs_data is not None

    # Build the pool (same way the client does)
    pool = [json.loads(entry.data) for entry in fs_data.message_pool]

    # Verify each event's refs resolve to the expected messages
    for i, ev in enumerate(fs_data.events):
        event_dict = ev.event
        assert isinstance(event_dict, dict)
        input_refs = event_dict.get("input_refs")
        assert input_refs is not None, f"Event {i} missing input_refs"

        resolved = _expand_refs(input_refs, pool)
        expected_contents = [m.content for m in expected_per_turn[i]]
        actual_contents = [m["content"] for m in resolved]
        assert actual_contents == expected_contents, (
            f"Event {i}: expected {expected_contents}, got {actual_contents}"
        )


def test_incremental_flush_pool_refs_correct(
    workspace: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Verify pool refs are correct when data is flushed incrementally across segments."""
    db, filestore = workspace
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    sys_msg = ChatMessageSystem(content="You are a helpful assistant.")
    scenario = ChatMessageUser(content="Scenario: decision theory problem")
    user1 = ChatMessageUser(content="What should I do?")
    asst1 = ChatMessageAssistant(content="I think you should cooperate.")
    tool1 = ChatMessageTool(content="Tool result: verified", tool_call_id="tc1")
    user2 = ChatMessageUser(content="Are you sure?")

    # Turn 1
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_event([sys_msg, scenario, user1]))]
    )

    # First flush → segment 1
    sync_to_filestore(db, filestore)

    # Turn 2
    db.log_events(
        [
            SampleEvent(
                id="s1",
                epoch=1,
                event=_make_event([sys_msg, scenario, user1, asst1, tool1, user2]),
            )
        ]
    )

    # Second flush → segment 2
    sync_to_filestore(db, filestore)

    # Simulate client's FIRST poll (no cursors) — reads all segments
    fs_data = filestore.get_sample_data("s1", 1)
    assert fs_data is not None

    pool = [json.loads(entry.data) for entry in fs_data.message_pool]

    # Verify turn 2's refs resolve correctly
    ev1 = fs_data.events[1].event
    assert isinstance(ev1, dict)
    resolved = _expand_refs(ev1["input_refs"], pool)
    expected = [sys_msg, scenario, user1, asst1, tool1, user2]
    actual_contents = [m["content"] for m in resolved]
    expected_contents = [m.content for m in expected]
    assert actual_contents == expected_contents

    # Simulate client's SECOND poll (with cursors from first poll)
    last_event_id = max(ev.id for ev in fs_data.events)
    last_pool_id = max(entry.id for entry in fs_data.message_pool)

    # Add turn 3
    asst2 = ChatMessageAssistant(content="Yes, confirmed.")
    user3 = ChatMessageUser(content="Great, thanks!")
    db.log_events(
        [
            SampleEvent(
                id="s1",
                epoch=1,
                event=_make_event(
                    [sys_msg, scenario, user1, asst1, tool1, user2, asst2, user3]
                ),
            )
        ]
    )
    sync_to_filestore(db, filestore)

    # Second poll with cursors
    fs_data2 = filestore.get_sample_data(
        "s1",
        1,
        after_event_id=last_event_id,
        after_message_pool_id=last_pool_id,
    )
    assert fs_data2 is not None

    # Append new pool entries to existing pool (client-side behavior)
    for entry in fs_data2.message_pool:
        pool.append(json.loads(entry.data))

    # Verify turn 3's refs resolve correctly against the combined pool
    assert len(fs_data2.events) == 1
    ev2 = fs_data2.events[0].event
    assert isinstance(ev2, dict)
    resolved2 = _expand_refs(ev2["input_refs"], pool)
    expected2 = [sys_msg, scenario, user1, asst1, tool1, user2, asst2, user3]
    actual2 = [m["content"] for m in resolved2]
    expected2_content = [m.content for m in expected2]
    assert actual2 == expected2_content


def test_two_samples_pool_isolation(
    workspace: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Verify pool refs are correct when two samples share a segment."""
    db, filestore = workspace
    sample_a = EvalSampleSummary(id="sA", epoch=1, input="test", target="target")
    sample_b = EvalSampleSummary(id="sB", epoch=1, input="test", target="target")
    db.start_sample(sample_a)
    db.start_sample(sample_b)

    # Interleave events from two samples
    msg_a1 = ChatMessageUser(content="Sample A message 1")
    msg_a2 = ChatMessageAssistant(content="Sample A response 1")
    msg_b1 = ChatMessageUser(content="Sample B message 1")
    msg_b2 = ChatMessageAssistant(content="Sample B response 1")

    db.log_events([SampleEvent(id="sA", epoch=1, event=_make_event([msg_a1]))])
    db.log_events([SampleEvent(id="sB", epoch=1, event=_make_event([msg_b1]))])
    db.log_events([SampleEvent(id="sA", epoch=1, event=_make_event([msg_a1, msg_a2]))])
    db.log_events([SampleEvent(id="sB", epoch=1, event=_make_event([msg_b1, msg_b2]))])

    sync_to_filestore(db, filestore)

    # Read sample A
    data_a = filestore.get_sample_data("sA", 1)
    assert data_a is not None
    pool_a = [json.loads(entry.data) for entry in data_a.message_pool]

    # Verify sample A's second event refs
    ev_a1 = data_a.events[1].event
    assert isinstance(ev_a1, dict)
    resolved_a = _expand_refs(ev_a1["input_refs"], pool_a)
    assert [m["content"] for m in resolved_a] == [
        "Sample A message 1",
        "Sample A response 1",
    ]

    # Read sample B
    data_b = filestore.get_sample_data("sB", 1)
    assert data_b is not None
    pool_b = [json.loads(entry.data) for entry in data_b.message_pool]

    # Verify sample B's second event refs
    ev_b1 = data_b.events[1].event
    assert isinstance(ev_b1, dict)
    resolved_b = _expand_refs(ev_b1["input_refs"], pool_b)
    assert [m["content"] for m in resolved_b] == [
        "Sample B message 1",
        "Sample B response 1",
    ]


def test_segment_with_no_new_pool_entries_does_not_duplicate(
    workspace: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Reproduces the cursor-reset bug.

    When a segment's flush adds events but no new pool entries,
    last_message_pool_id is 0; the next flush must not treat that as "we have
    nothing yet" and re-include all earlier pool entries.
    """
    db, filestore = workspace
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    sys_msg = ChatMessageSystem(content="You are a helpful assistant.")
    user1 = ChatMessageUser(content="Question 1")
    user2 = ChatMessageUser(content="Question 2")

    # Flush 1: introduces 2 pool entries [sys_msg, user1].
    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_event([sys_msg, user1]))])
    sync_to_filestore(db, filestore)

    # Flush 2: same messages → no new pool entries → segment's
    # last_message_pool_id = 0 (this is the bug trigger).
    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_event([sys_msg, user1]))])
    sync_to_filestore(db, filestore)

    # Flush 3: one new message. The cursor for this sync must reflect that
    # we already have pool entries up to id=2; otherwise the new segment will
    # re-include [sys_msg, user1].
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_event([sys_msg, user1, user2]))]
    )
    sync_to_filestore(db, filestore)

    # Initial poll (no cursors) — the client gets the union of all segments.
    fs_data = filestore.get_sample_data("s1", 1)
    assert fs_data is not None

    pool_ids = [entry.id for entry in fs_data.message_pool]
    assert len(pool_ids) == len(set(pool_ids)), f"duplicate pool entry ids: {pool_ids}"

    # Refs must resolve to the right messages.
    pool = [json.loads(entry.data) for entry in fs_data.message_pool]
    last_event = fs_data.events[-1].event
    assert isinstance(last_event, dict)
    resolved = _expand_refs(last_event["input_refs"], pool)
    assert [m["content"] for m in resolved] == [
        "You are a helpful assistant.",
        "Question 1",
        "Question 2",
    ]


def test_segment_with_no_new_call_pool_entries_does_not_duplicate(
    workspace: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Same cursor-reset bug, but for the call_pool path.

    `last_call_pool_id` zeroes out when a segment adds events whose calls
    contain no new request messages; the next sync must not re-include the
    call_pool entries already written.
    """
    db, filestore = workspace
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    call_a = [{"role": "user", "content": "call A"}]
    call_b = [{"role": "user", "content": "call B"}]

    # Flush 1: introduces 1 call_pool entry.
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_event([], call_msgs=call_a))]
    )
    sync_to_filestore(db, filestore)

    # Flush 2: same call request → no new call_pool entries → bug trigger.
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_event([], call_msgs=call_a))]
    )
    sync_to_filestore(db, filestore)

    # Flush 3: a new call request.
    db.log_events(
        [
            SampleEvent(
                id="s1", epoch=1, event=_make_event([], call_msgs=call_a + call_b)
            )
        ]
    )
    sync_to_filestore(db, filestore)

    fs_data = filestore.get_sample_data("s1", 1)
    assert fs_data is not None

    call_ids = [entry.id for entry in fs_data.call_pool]
    assert len(call_ids) == len(set(call_ids)), (
        f"duplicate call_pool entry ids: {call_ids}"
    )


def test_per_sample_cursor_with_interleaved_samples(
    workspace: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Cursor must scan the sample's own segments, not just the manifest's last.

    Sample A's segments are non-contiguous (segment 2 belongs to sample B
    only), and sample A's later segments add events without new pool entries.
    The cursor for sample A must ignore segment 2 entirely and still recover
    the correct max from segment 1.
    """
    db, filestore = workspace
    sample_a = EvalSampleSummary(id="sA", epoch=1, input="test", target="target")
    sample_b = EvalSampleSummary(id="sB", epoch=1, input="test", target="target")
    db.start_sample(sample_a)
    db.start_sample(sample_b)

    a_msg1 = ChatMessageUser(content="A1")
    a_msg2 = ChatMessageUser(content="A2")
    b_msg = ChatMessageUser(content="B1")

    # Segment 1: sample A only, contributes pool entries [a_msg1, a_msg2].
    db.log_events([SampleEvent(id="sA", epoch=1, event=_make_event([a_msg1, a_msg2]))])
    sync_to_filestore(db, filestore)

    # Segment 2: sample B only. A is absent here.
    db.log_events([SampleEvent(id="sB", epoch=1, event=_make_event([b_msg]))])
    sync_to_filestore(db, filestore)

    # Segment 3: sample A, same messages as before → events only, no new pool.
    db.log_events([SampleEvent(id="sA", epoch=1, event=_make_event([a_msg1, a_msg2]))])
    sync_to_filestore(db, filestore)

    # Segment 4: sample A adds a new message. Cursor must come from segment 1
    # (which A was in), not segment 3 (which has last_message_pool_id=0) and
    # not segment 2 (which A was never in).
    a_msg3 = ChatMessageUser(content="A3")
    db.log_events(
        [SampleEvent(id="sA", epoch=1, event=_make_event([a_msg1, a_msg2, a_msg3]))]
    )
    sync_to_filestore(db, filestore)

    data_a = filestore.get_sample_data("sA", 1)
    assert data_a is not None

    pool_ids = [entry.id for entry in data_a.message_pool]
    assert len(pool_ids) == len(set(pool_ids)), (
        f"duplicate pool ids for sample A: {pool_ids}"
    )

    pool_a = [json.loads(entry.data) for entry in data_a.message_pool]
    last_event = data_a.events[-1].event
    assert isinstance(last_event, dict)
    resolved = _expand_refs(last_event["input_refs"], pool_a)
    assert [m["content"] for m in resolved] == ["A1", "A2", "A3"]
