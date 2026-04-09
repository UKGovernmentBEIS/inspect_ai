"""Tests for reading recovery data from the sample buffer database."""

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._recover import BufferRecoveryData, read_buffer_recovery_data
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer._metric import Score


def _make_started_summary(id: int, epoch: int = 1) -> EvalSampleSummary:
    """Create a summary for a sample that just started (no scores, no completed_at)."""
    return EvalSampleSummary(
        id=id,
        epoch=epoch,
        input=f"input {id}",
        target=f"target {id}",
        started_at=datetime.now(timezone.utc).isoformat(),
    )


def _make_completed_summary(id: int, epoch: int = 1) -> EvalSampleSummary:
    """Create a summary for a completed sample (has scores and completed_at)."""
    return EvalSampleSummary(
        id=id,
        epoch=epoch,
        input=f"input {id}",
        target=f"target {id}",
        scores={"accuracy": Score(value="C", answer="C")},
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )


def _make_model_event(content: str = "test response") -> ModelEvent:
    """Create a simple ModelEvent for testing."""
    from inspect_ai.model._generate_config import GenerateConfig

    return ModelEvent(
        model="mockllm/model",
        input=[ChatMessageUser(content="test input")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content(model="mockllm/model", content=content),
    )


def _create_test_buffer(
    location: str,
    completed_ids: list[int],
    in_progress_ids: list[int],
    db_dir: str,
) -> SampleBufferDatabase:
    """Create a test buffer DB with a mix of completed and in-progress samples."""
    buffer = SampleBufferDatabase(location, create=True, db_dir=Path(db_dir))

    # Start and complete some samples
    for id in completed_ids:
        started = _make_started_summary(id)
        buffer.start_sample(started)
        buffer.log_events(
            [SampleEvent(id=id, epoch=1, event=_make_model_event(f"output {id}"))]
        )
        completed = _make_completed_summary(id)
        buffer.complete_sample(completed)

    # Start but don't complete others (simulating crash)
    for id in in_progress_ids:
        started = _make_started_summary(id)
        buffer.start_sample(started)
        buffer.log_events(
            [SampleEvent(id=id, epoch=1, event=_make_model_event(f"partial {id}"))]
        )

    return buffer


def test_read_buffer_recovery_data_mixed() -> None:
    """Test reading buffer DB with mix of completed and in-progress samples."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")
        location = os.path.join(temp_dir, "test.eval")

        _create_test_buffer(
            location,
            completed_ids=[1, 2],
            in_progress_ids=[3, 4],
            db_dir=db_dir,
        )

        recovery = read_buffer_recovery_data(location, db_dir=db_dir)

        assert recovery is not None
        assert isinstance(recovery, BufferRecoveryData)
        assert len(recovery.completed) == 2
        assert len(recovery.in_progress) == 2

        # Completed samples have completed_at and scores
        for sample in recovery.completed:
            assert sample.completed_at is not None
            assert sample.scores is not None

        # In-progress samples don't
        for sample in recovery.in_progress:
            assert sample.completed_at is None


def test_read_buffer_recovery_data_events_accessible() -> None:
    """Test that per-sample events are accessible via the buffer handle."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")
        location = os.path.join(temp_dir, "test.eval")

        _create_test_buffer(
            location,
            completed_ids=[1],
            in_progress_ids=[2],
            db_dir=db_dir,
        )

        recovery = read_buffer_recovery_data(location, db_dir=db_dir)
        assert recovery is not None
        assert recovery.buffer is not None

        # Can get events for completed sample
        data = recovery.buffer.get_sample_data(1, 1)
        assert data is not None
        assert len(data.events) > 0

        # Can get events for in-progress sample
        data = recovery.buffer.get_sample_data(2, 1)
        assert data is not None
        assert len(data.events) > 0


def test_read_buffer_recovery_data_no_db() -> None:
    """Test that missing buffer DB returns None."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")
        location = os.path.join(temp_dir, "nonexistent.eval")

        result = read_buffer_recovery_data(location, db_dir=db_dir)
        assert result is None


def test_read_buffer_recovery_data_empty() -> None:
    """Test buffer DB with no samples (all were flushed before crash)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")
        location = os.path.join(temp_dir, "test.eval")

        # Create DB but don't add any samples
        SampleBufferDatabase(location, create=True, db_dir=Path(db_dir))

        recovery = read_buffer_recovery_data(location, db_dir=db_dir)
        assert recovery is not None
        assert len(recovery.completed) == 0
        assert len(recovery.in_progress) == 0


def test_read_buffer_recovery_data_all_completed() -> None:
    """Test buffer DB where all samples completed before crash."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")
        location = os.path.join(temp_dir, "test.eval")

        _create_test_buffer(
            location,
            completed_ids=[1, 2, 3],
            in_progress_ids=[],
            db_dir=db_dir,
        )

        recovery = read_buffer_recovery_data(location, db_dir=db_dir)
        assert recovery is not None
        assert len(recovery.completed) == 3
        assert len(recovery.in_progress) == 0


def test_read_buffer_recovery_data_all_in_progress() -> None:
    """Test buffer DB where all samples were in-progress at crash."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")
        location = os.path.join(temp_dir, "test.eval")

        _create_test_buffer(
            location,
            completed_ids=[],
            in_progress_ids=[1, 2],
            db_dir=db_dir,
        )

        recovery = read_buffer_recovery_data(location, db_dir=db_dir)
        assert recovery is not None
        assert len(recovery.completed) == 0
        assert len(recovery.in_progress) == 2
