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


_DEAD_PID = 99999999


def _create_test_buffer(
    location: str,
    completed_ids: list[int],
    in_progress_ids: list[int],
    db_dir: str,
) -> SampleBufferDatabase:
    """Create a test buffer DB with a dead PID (simulating crashed process)."""
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

    # Rename DB to dead PID to simulate crashed process
    old_path = buffer.db_path
    new_path = old_path.parent / old_path.name.replace(
        f".{os.getpid()}.", f".{_DEAD_PID}."
    )
    old_path.rename(new_path)
    buffer.db_path = new_path

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

        # Create DB but don't add any samples, simulate dead PID
        buffer = SampleBufferDatabase(location, create=True, db_dir=Path(db_dir))
        old_path = buffer.db_path
        new_path = old_path.parent / old_path.name.replace(
            f".{os.getpid()}.", f".{_DEAD_PID}."
        )
        old_path.rename(new_path)

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


def test_read_buffer_recovery_data_picks_newest_db() -> None:
    """Test that when multiple dead-PID DBs exist, the newest one is used."""
    import time

    from inspect_ai._util.file import filesystem
    from inspect_ai.log._recorders.buffer.database import (
        location_dir_and_file,
        resolve_db_dir,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")
        location = os.path.join(temp_dir, "test.eval")

        # Resolve the subdirectory where DBs are stored
        resolved_dir = resolve_db_dir(Path(db_dir))
        uri = filesystem(location).path_as_uri(location)
        dir_hash, file = location_dir_and_file(uri)
        log_subdir = resolved_dir / dir_hash
        log_subdir.mkdir(parents=True, exist_ok=True)

        # Create an older DB with dead PID 99999998
        older_pid = 99999998
        older_db = log_subdir / f"{file}.{older_pid}.db"
        older_buffer = SampleBufferDatabase(location, create=True, db_dir=Path(db_dir))
        # Add a sample to the older DB
        older_buffer.start_sample(_make_started_summary(1))
        older_buffer.log_events(
            [SampleEvent(id=1, epoch=1, event=_make_model_event("old response"))]
        )
        older_buffer.complete_sample(_make_completed_summary(1))
        # Rename to dead PID
        older_buffer.db_path.rename(older_db)

        # Small delay to ensure different mtime
        time.sleep(0.1)

        # Create a newer DB with dead PID 99999999
        newer_pid = _DEAD_PID
        newer_db = log_subdir / f"{file}.{newer_pid}.db"
        newer_buffer = SampleBufferDatabase(location, create=True, db_dir=Path(db_dir))
        # Add different samples to the newer DB
        newer_buffer.start_sample(_make_started_summary(10))
        newer_buffer.log_events(
            [SampleEvent(id=10, epoch=1, event=_make_model_event("new response"))]
        )
        newer_buffer.complete_sample(_make_completed_summary(10))
        newer_buffer.start_sample(_make_started_summary(11))
        newer_buffer.log_events(
            [SampleEvent(id=11, epoch=1, event=_make_model_event("new partial"))]
        )
        # Rename to dead PID
        newer_buffer.db_path.rename(newer_db)

        # Read recovery data — should pick the newer DB
        recovery = read_buffer_recovery_data(location, db_dir=db_dir)
        assert recovery is not None
        # Newer DB has 1 completed (id=10) and 1 in-progress (id=11)
        assert len(recovery.completed) == 1
        assert recovery.completed[0].id == 10
        assert len(recovery.in_progress) == 1
        assert recovery.in_progress[0].id == 11
