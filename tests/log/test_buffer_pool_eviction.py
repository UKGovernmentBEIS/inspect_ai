import tempfile
from pathlib import Path
from typing import Generator

import pytest

from inspect_ai.event._compaction import CompactionEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer import SampleBufferDatabase
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput


@pytest.fixture
def db() -> Generator[SampleBufferDatabase, None, None]:
    with tempfile.TemporaryDirectory() as db_dir:
        test_db = SampleBufferDatabase(location="test_location", db_dir=Path(db_dir))
        yield test_db
        test_db.cleanup()


def _make_model_event(input_msgs: list) -> ModelEvent:
    return ModelEvent(
        model="test-model",
        input=input_msgs,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
    )


def _make_model_event_with_call(input_msgs: list, call_messages: list) -> ModelEvent:
    event = _make_model_event(input_msgs)
    return event.model_copy(
        update={
            "call": ModelCall(
                request={"model": "test", "messages": call_messages},
                response={"id": "r1", "choices": []},
            )
        }
    )


def test_compaction_event_nulls_pool_entries(db: SampleBufferDatabase) -> None:
    """CompactionEvent nulls pool list entries but preserves the index."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    msg_a = ChatMessageUser(content="Hello")
    msg_b = ChatMessageAssistant(content="Hi there")

    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a]))])
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a, msg_b]))]
    )

    key = ("s1", 1)
    pool, index = db._msg_pools[key]
    pool_len_before = len(pool)
    assert pool_len_before > 0
    assert all(entry is not None for entry in pool)

    compaction_event = CompactionEvent(
        type="summary",
        source="inspect",
        tokens_before=1000,
        tokens_after=200,
    )
    db.log_events([SampleEvent(id="s1", epoch=1, event=compaction_event)])

    pool, index = db._msg_pools[key]
    assert len(pool) == pool_len_before
    assert all(entry is None for entry in pool)


def test_new_messages_append_after_eviction(db: SampleBufferDatabase) -> None:
    """After pool eviction, new messages append correctly to the pool."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    msg_a = ChatMessageUser(content="Hello")
    msg_b = ChatMessageAssistant(content="Hi there")

    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a]))])
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a, msg_b]))]
    )

    key = ("s1", 1)
    pool_len_before_compaction = len(db._msg_pools[key][0])

    compaction_event = CompactionEvent(
        type="summary", source="inspect", tokens_before=1000, tokens_after=200
    )
    db.log_events([SampleEvent(id="s1", epoch=1, event=compaction_event)])

    msg_c = ChatMessageUser(content="Compacted summary of conversation")
    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_c]))])

    pool, index = db._msg_pools[key]

    # Pool grew by the new message(s)
    assert len(pool) > pool_len_before_compaction
    # Old entries are still None
    for i in range(pool_len_before_compaction):
        assert pool[i] is None
    # New entry at the end is not None
    assert pool[-1] is not None
    assert pool[-1].content == "Compacted summary of conversation"

    # DB still returns data
    data = db.get_sample_data("s1", 1)
    assert data is not None
    assert len(data.message_pool) > 0


def test_multi_sample_pool_eviction_is_isolated(db: SampleBufferDatabase) -> None:
    """Compaction on one sample does not affect another sample's pool."""
    sample1 = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    sample2 = EvalSampleSummary(id="s2", epoch=1, input="test", target="target")
    db.start_sample(sample1)
    db.start_sample(sample2)

    msg_a = ChatMessageUser(content="Hello from s1")
    msg_b = ChatMessageUser(content="Hello from s2")

    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a]))])
    db.log_events([SampleEvent(id="s2", epoch=1, event=_make_model_event([msg_b]))])

    key1 = ("s1", 1)
    key2 = ("s2", 1)
    assert len(db._msg_pools[key1][0]) > 0
    assert len(db._msg_pools[key2][0]) > 0

    # Compact only s1
    compaction_event = CompactionEvent(
        type="summary", source="inspect", tokens_before=1000, tokens_after=200
    )
    db.log_events([SampleEvent(id="s1", epoch=1, event=compaction_event)])

    # s1 pool entries are nulled
    pool1, _ = db._msg_pools[key1]
    assert all(entry is None for entry in pool1)

    # s2 pool entries are untouched
    pool2, _ = db._msg_pools[key2]
    assert all(entry is not None for entry in pool2)


def test_call_pool_eviction(db: SampleBufferDatabase) -> None:
    """CompactionEvent also nulls call pool entries."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    call_msgs = [{"role": "user", "content": "Hello"}]
    db.log_events(
        [
            SampleEvent(
                id="s1",
                epoch=1,
                event=_make_model_event_with_call(
                    [ChatMessageUser(content="Hello")], call_msgs
                ),
            )
        ]
    )

    key = ("s1", 1)
    call_pool, call_index = db._call_pools[key]
    assert len(call_pool) > 0
    assert all(entry is not None for entry in call_pool)

    compaction_event = CompactionEvent(
        type="summary", source="inspect", tokens_before=1000, tokens_after=200
    )
    db.log_events([SampleEvent(id="s1", epoch=1, event=compaction_event)])

    call_pool, call_index = db._call_pools[key]
    assert all(entry is None for entry in call_pool)


def test_compaction_without_prior_pool_is_noop(db: SampleBufferDatabase) -> None:
    """CompactionEvent on a sample with no pool entries doesn't error."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    compaction_event = CompactionEvent(
        type="summary", source="inspect", tokens_before=1000, tokens_after=200
    )
    # Should not raise
    db.log_events([SampleEvent(id="s1", epoch=1, event=compaction_event)])

    # Pools should not exist for this key
    key = ("s1", 1)
    assert key not in db._msg_pools
    assert key not in db._call_pools
