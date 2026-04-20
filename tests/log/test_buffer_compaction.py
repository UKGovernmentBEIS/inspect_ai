import tempfile
from pathlib import Path
from typing import Generator

import pytest

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer import SampleBufferDatabase
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
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


def test_vacuum_after_remove_samples(db: SampleBufferDatabase) -> None:
    """DB file shrinks after remove_samples due to VACUUM."""
    for i in range(20):
        sample_id = f"s{i}"
        sample = EvalSampleSummary(id=sample_id, epoch=1, input="test", target="target")
        db.start_sample(sample)
        for j in range(10):
            msg = ChatMessageUser(content=f"Message {i}-{j} " + "x" * 500)
            db.log_events(
                [SampleEvent(id=sample_id, epoch=1, event=_make_model_event([msg]))]
            )

    size_before = db.db_path.stat().st_size
    assert size_before > 0

    db.remove_samples([(f"s{i}", 1) for i in range(20)])

    size_after = db.db_path.stat().st_size

    assert size_after < size_before * 0.5, (
        f"Expected significant shrinkage: before={size_before}, after={size_after}"
    )


def test_shrink_memory_on_sync(db: SampleBufferDatabase) -> None:
    """PRAGMA shrink_memory executes without error."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    msg = ChatMessageUser(content="Hello")
    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg]))])

    db._shrink_memory()
