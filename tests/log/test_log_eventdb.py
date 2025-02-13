import os
from typing import Generator

import pytest
from shortuuid import uuid

from inspect_ai.log._log import EvalSample
from inspect_ai.log._recorders.events import JsonData, SampleEventDatabase


@pytest.fixture
def db() -> Generator[SampleEventDatabase, None, None]:
    """Fixture to create and cleanup a test database."""
    test_db = SampleEventDatabase(location="test_location")
    yield test_db
    test_db.cleanup()


@pytest.fixture
def sample() -> Generator[EvalSample, None, None]:
    yield EvalSample(id=uuid(), epoch=1, input="test input", target="test target")


def test_database_initialization(db: SampleEventDatabase) -> None:
    """Test that the database is properly initialized."""
    assert os.path.exists(db.db_path)
    assert db.location == "test_location"


def test_start_sample(db: SampleEventDatabase, sample: EvalSample) -> None:
    """Test starting a new sample."""
    db.start_sample(id="sample1", epoch=1, sample=sample)

    # Verify the sample was created
    samples = list(db.get_samples())
    assert len(samples) == 1
    assert samples[0].id == "sample1"
    assert samples[0].epoch == 1
    assert samples[0].sample == sample
    assert samples[0].summary is None


def test_log_events(db: SampleEventDatabase, sample: EvalSample) -> None:
    """Test logging events for a sample."""
    # First create a sample
    db.start_sample(id="sample1", epoch=1, sample=sample)

    # Log some events
    events: list[JsonData] = [
        {"type": "start", "timestamp": "2024-02-13T10:00:00"},
        {"type": "progress", "timestamp": "2024-02-13T10:00:01"},
    ]
    event_ids = db.log_events(id="sample1", epoch=1, events=events)

    # Verify events were logged
    assert len(event_ids) == 2
    logged_events = list(db.get_events(id="sample1", epoch=1))
    assert len(logged_events) == 2
    assert {k: v for k, v in logged_events[0].event.items() if k != "id"} == events[0]
    assert {k: v for k, v in logged_events[1].event.items() if k != "id"} == events[1]


def test_complete_sample(db: SampleEventDatabase, sample: EvalSample) -> None:
    """Test completing a sample with a summary."""
    # Create sample
    db.start_sample(id="sample1", epoch=1, sample=sample)

    # Complete sample
    summary_data: JsonData = {"result": "success", "metrics": {"accuracy": 0.95}}
    db.complete_sample(id="sample1", epoch=1, summary=summary_data)

    # Verify summary was added
    samples = list(db.get_samples())
    assert len(samples) == 1
    assert samples[0].summary == summary_data


def test_get_events_with_filters(db: SampleEventDatabase) -> None:
    """Test getting events with various filters."""
    # Create two samples with events
    sample1 = EvalSample(id="sample1", epoch=1, input="test1", target="test target")
    sample2 = EvalSample(id="sample2", epoch=1, input="test2", target="test target")
    db.start_sample(id="sample1", epoch=1, sample=sample1)
    db.start_sample(id="sample2", epoch=1, sample=sample2)

    events1: list[JsonData] = [{"type": "start", "sample": "1"}]
    events2: list[JsonData] = [{"type": "start", "sample": "2"}]

    db.log_events(id="sample1", epoch=1, events=events1)
    db.log_events(id="sample2", epoch=1, events=events2)

    # Test filtering by sample
    filtered_events = list(db.get_events(id="sample1", epoch=1))
    assert len(filtered_events) == 1
    assert filtered_events[0].event["type"] == events1[0]["type"]
    assert filtered_events[0].event["sample"] == events1[0]["sample"]

    # Test getting all events
    all_events = list(db.get_events())
    assert len(all_events) == 2


def test_error_cases(db: SampleEventDatabase) -> None:
    """Test various error cases."""
    # Test logging events for non-existent sample
    with pytest.raises(ValueError):
        test_event: list[JsonData] = [{"type": "test"}]
        db.log_events(id="nonexistent", epoch=1, events=test_event)

    # Test completing non-existent sample
    with pytest.raises(ValueError):
        summary: JsonData = {"status": "done"}
        db.complete_sample(id="nonexistent", epoch=1, summary=summary)

    # Test invalid get_events parameters
    with pytest.raises(ValueError):
        list(db.get_events(id="sample1", epoch=None))


def test_concurrent_samples(db: SampleEventDatabase) -> None:
    """Test handling multiple samples concurrently."""
    # Create multiple samples
    samples: list[tuple[str, int, EvalSample]] = [
        (
            "sample1",
            1,
            EvalSample(id="sample1", epoch=1, input="test1", target="target"),
        ),
        (
            "sample1",
            2,
            EvalSample(id="sample1", epoch=2, input="test1_v2", target="target"),
        ),
        (
            "sample2",
            1,
            EvalSample(id="sample2", epoch=1, input="test2", target="target"),
        ),
    ]

    sample_ids = []
    for sample_id, epoch, data in samples:
        sample_ids.append(db.start_sample(id=sample_id, epoch=epoch, sample=data))

    # Verify all samples were created
    stored_samples = list(db.get_samples())
    assert len(stored_samples) == 3

    # Verify we can get specific samples
    events: list[JsonData] = [{"type": "test"}]
    db.log_events(id="sample1", epoch=1, events=events)
    db.log_events(id="sample1", epoch=2, events=events)

    # Check events for specific epoch
    events_epoch_1 = list(db.get_events(id="sample1", epoch=1))
    assert len(events_epoch_1) == 1

    events_epoch_2 = list(db.get_events(id="sample1", epoch=2))
    assert len(events_epoch_2) == 1


def test_cleanup(db: SampleEventDatabase, sample: EvalSample) -> None:
    """Test database cleanup."""
    # Create some data
    db.start_sample(id="sample1", epoch=1, sample=sample)

    # Verify file exists
    assert os.path.exists(db.db_path)

    # Cleanup
    db.cleanup()

    # Verify file is gone
    assert not os.path.exists(db.db_path)

    # Verify cleanup is idempotent
    db.cleanup()  # Should not raise any errors
