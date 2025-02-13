import os
from typing import Generator

import pytest

from inspect_ai.log._recorders.eventdb.eventdb import JsonData, SampleEventDatabase


@pytest.fixture
def db() -> Generator[SampleEventDatabase, None, None]:
    """Fixture to create and cleanup a test database."""
    test_db = SampleEventDatabase(location="test_location")
    yield test_db
    test_db.cleanup()


def test_database_initialization(db: SampleEventDatabase) -> None:
    """Test that the database is properly initialized."""
    assert os.path.exists(db.db_path)
    assert db.location == "test_location"


def test_start_sample(db: SampleEventDatabase) -> None:
    """Test starting a new sample."""
    sample_data: JsonData = {"input": "test input", "target": "test target"}
    db.start_sample(id="sample1", epoch=1, sample=sample_data)

    # Verify the sample was created
    samples = list(db.get_samples())
    assert len(samples) == 1
    assert samples[0].id == "sample1"
    assert samples[0].epoch == 1
    assert samples[0].sample == sample_data
    assert samples[0].summary is None


def test_log_events(db: SampleEventDatabase) -> None:
    """Test logging events for a sample."""
    # First create a sample
    sample_data: JsonData = {"input": "test input"}
    db.start_sample(id="sample1", epoch=1, sample=sample_data)

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


def test_complete_sample(db: SampleEventDatabase) -> None:
    """Test completing a sample with a summary."""
    # Create sample
    sample_data: JsonData = {"input": "test input"}
    db.start_sample(id="sample1", epoch=1, sample=sample_data)

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
    db.start_sample(id="sample1", epoch=1, sample={"input": "test1"})
    db.start_sample(id="sample2", epoch=1, sample={"input": "test2"})

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
    samples: list[tuple[str, int, JsonData]] = [
        ("sample1", 1, {"input": "test1"}),
        ("sample1", 2, {"input": "test1_v2"}),  # Same ID, different epoch
        ("sample2", 1, {"input": "test2"}),
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


def test_cleanup(db: SampleEventDatabase) -> None:
    """Test database cleanup."""
    # Create some data
    sample_data: JsonData = {"input": "test"}
    db.start_sample(id="sample1", epoch=1, sample=sample_data)

    # Verify file exists
    assert os.path.exists(db.db_path)

    # Cleanup
    db.cleanup()

    # Verify file is gone
    assert not os.path.exists(db.db_path)

    # Verify cleanup is idempotent
    db.cleanup()  # Should not raise any errors
