"""Cursor computation in sync_to_filestore.

For each sample, the next sync's cursor takes the max of last_*_id across
all of the sample's segments — including segments whose last_*_id is 0
because no items of that type were added there (e.g. a flush that records
events but no new pool entries) and segments the sample did not appear in.
These tests pin that invariant on the message_pool path, the call_pool
path, and a multi-sample case where the affected sample's segments are
non-contiguous.
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
from inspect_ai.log._recorders.buffer.types import SampleData
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageSystem,
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


def _log(
    db: SampleBufferDatabase,
    sid: str,
    msgs: list[ChatMessage],
    call_msgs: Any = None,
) -> None:
    db.log_events(
        [SampleEvent(id=sid, epoch=1, event=_make_event(msgs, call_msgs=call_msgs))]
    )


def _expand_refs(refs: Any, pool: list) -> list:
    assert isinstance(refs, list)
    result = []
    for start, end in refs:
        result.extend(pool[start:end])
    return result


def _resolved_contents(fs_data: SampleData, idx: int = -1) -> list[str]:
    """Resolve `input_refs` of the event at `idx` against `fs_data.message_pool`."""
    pool = [json.loads(entry.data) for entry in fs_data.message_pool]
    event = fs_data.events[idx].event
    assert isinstance(event, dict)
    return [m["content"] for m in _expand_refs(event["input_refs"], pool)]


def test_segment_with_no_new_pool_entries_does_not_duplicate(
    workspace: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Cursor stays correct across a segment with events but no new message_pool entries.

    Such a segment records `last_message_pool_id = 0`; the next sync must
    take its cursor from the earlier segment that contributed the entries,
    not from the latest segment alone.
    """
    db, filestore = workspace
    db.start_sample(EvalSampleSummary(id="s1", epoch=1, input="test", target="target"))

    sys_msg = ChatMessageSystem(content="You are a helpful assistant.")
    user1 = ChatMessageUser(content="Question 1")
    user2 = ChatMessageUser(content="Question 2")

    # Flush 1: introduces 2 pool entries [sys_msg, user1].
    _log(db, "s1", [sys_msg, user1])
    sync_to_filestore(db, filestore)

    # Flush 2: same messages → no new pool entries → segment's
    # last_message_pool_id is 0.
    _log(db, "s1", [sys_msg, user1])
    sync_to_filestore(db, filestore)

    # Flush 3: one new message. The cursor for this sync must come from
    # segment 1 (last_message_pool_id=2), not segment 2's 0, so the new
    # segment contains only the new entry [user2].
    _log(db, "s1", [sys_msg, user1, user2])
    sync_to_filestore(db, filestore)

    fs_data = filestore.get_sample_data("s1", 1)
    assert fs_data is not None

    pool_ids = [entry.id for entry in fs_data.message_pool]
    assert len(pool_ids) == len(set(pool_ids)), f"duplicate pool entry ids: {pool_ids}"
    assert _resolved_contents(fs_data) == [
        "You are a helpful assistant.",
        "Question 1",
        "Question 2",
    ]


def test_segment_with_no_new_call_pool_entries_does_not_duplicate(
    workspace: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Cursor stays correct across a segment with events but no new call_pool entries.

    A segment whose events carry only previously-seen call requests records
    `last_call_pool_id = 0`; the next sync must still resume from the prior
    `last_call_pool_id`, not re-include the call_pool entries already written.
    """
    db, filestore = workspace
    db.start_sample(EvalSampleSummary(id="s1", epoch=1, input="test", target="target"))

    call_a = [{"role": "user", "content": "call A"}]
    call_b = [{"role": "user", "content": "call B"}]

    # Flush 1: introduces 1 call_pool entry.
    _log(db, "s1", [], call_msgs=call_a)
    sync_to_filestore(db, filestore)

    # Flush 2: same call request → no new call_pool entries → segment's
    # last_call_pool_id is 0.
    _log(db, "s1", [], call_msgs=call_a)
    sync_to_filestore(db, filestore)

    # Flush 3: a new call request.
    _log(db, "s1", [], call_msgs=call_a + call_b)
    sync_to_filestore(db, filestore)

    fs_data = filestore.get_sample_data("s1", 1)
    assert fs_data is not None

    call_ids = [entry.id for entry in fs_data.call_pool]
    assert len(call_ids) == len(set(call_ids)), (
        f"duplicate call_pool entry ids: {call_ids}"
    )
    calls = [json.loads(entry.data) for entry in fs_data.call_pool]
    assert calls == [
        {"role": "user", "content": "call A"},
        {"role": "user", "content": "call B"},
    ]


def test_per_sample_cursor_with_interleaved_samples(
    workspace: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Cursor for a sample is computed from that sample's own segments only.

    Sample A's segments are non-contiguous (sample B contributes segment 2,
    which sample A is not in), and sample A's later segments add events
    without new pool entries. The cursor for sample A must come from
    segment 1, not segment 3 (whose `last_message_pool_id` is 0) and not
    segment 2 (which sample A was never in).
    """
    db, filestore = workspace
    db.start_sample(EvalSampleSummary(id="sA", epoch=1, input="test", target="target"))
    db.start_sample(EvalSampleSummary(id="sB", epoch=1, input="test", target="target"))

    a_msg1 = ChatMessageUser(content="A1")
    a_msg2 = ChatMessageUser(content="A2")
    b_msg = ChatMessageUser(content="B1")

    # Segment 1: sample A only, contributes pool entries [a_msg1, a_msg2].
    _log(db, "sA", [a_msg1, a_msg2])
    sync_to_filestore(db, filestore)

    # Segment 2: sample B only. A is absent here.
    _log(db, "sB", [b_msg])
    sync_to_filestore(db, filestore)

    # Segment 3: sample A, same messages as before → events only, no new pool.
    _log(db, "sA", [a_msg1, a_msg2])
    sync_to_filestore(db, filestore)

    # Segment 4: sample A adds a new message. Cursor must come from segment 1
    # (which A was in), not segment 3 (which has last_message_pool_id=0) and
    # not segment 2 (which A was never in).
    a_msg3 = ChatMessageUser(content="A3")
    _log(db, "sA", [a_msg1, a_msg2, a_msg3])
    sync_to_filestore(db, filestore)

    data_a = filestore.get_sample_data("sA", 1)
    assert data_a is not None

    pool_ids = [entry.id for entry in data_a.message_pool]
    assert len(pool_ids) == len(set(pool_ids)), (
        f"duplicate pool ids for sample A: {pool_ids}"
    )
    assert _resolved_contents(data_a) == ["A1", "A2", "A3"]

    # Sample B's data must not have been corrupted by sample A's writes.
    data_b = filestore.get_sample_data("sB", 1)
    assert data_b is not None
    assert _resolved_contents(data_b) == ["B1"]
