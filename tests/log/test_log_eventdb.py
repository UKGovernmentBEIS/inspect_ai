import os
import tempfile
from pathlib import Path
from sqlite3 import IntegrityError
from typing import Generator

import pytest

from inspect_ai.log._recorders.events import SampleEventDatabase
from inspect_ai.log._recorders.types import SampleSummary
from inspect_ai.log._transcript import Event, InfoEvent


@pytest.fixture
def db() -> Generator[SampleEventDatabase, None, None]:
    """Fixture to create and cleanup a test database."""
    with tempfile.TemporaryDirectory() as db_dir:
        test_db = SampleEventDatabase(location="test_location", db_dir=Path(db_dir))
        yield test_db
        test_db.cleanup()


@pytest.fixture
def sample() -> Generator[SampleSummary, None, None]:
    yield SampleSummary(id="sample1", epoch=1, input="test input", target="test target")


def test_database_initialization(db: SampleEventDatabase) -> None:
    """Test that the database is properly initialized."""
    assert os.path.exists(db.db_path)
    assert db.location == "test_location"


def test_start_sample(db: SampleEventDatabase, sample: SampleSummary) -> None:
    """Test starting a new sample."""
    db.start_sample(sample=sample)

    # Verify the sample was created
    samples = list(db.get_samples())
    assert len(samples) == 1
    assert samples[0].id == "sample1"
    assert samples[0].epoch == 1
    assert samples[0].sample == sample


def test_log_events(db: SampleEventDatabase, sample: SampleSummary) -> None:
    """Test logging events for a sample."""
    # First create a sample
    db.start_sample(sample=sample)

    # Log some events
    events: list[Event] = [InfoEvent(data="event1"), InfoEvent(data="event2")]
    db.log_events(id="sample1", epoch=1, events=events)

    # Verify events were logged
    logged_events = list(db.get_events(id="sample1", epoch=1))
    assert len(logged_events) == 2


def test_complete_sample(db: SampleEventDatabase, sample: SampleSummary) -> None:
    """Test completing a sample with a summary."""
    # Create sample
    db.start_sample(sample=sample)

    # Complete sample
    summary = SampleSummary(
        id=sample.id, epoch=sample.epoch, input=sample.input, target=sample.target
    )
    db.complete_sample(summary=summary)

    # Verify summary was added
    samples = list(db.get_samples())
    assert len(samples) == 1
    assert samples[0].sample == summary


def test_get_events_with_filters(db: SampleEventDatabase) -> None:
    """Test getting events with various filters."""
    # Create two samples with events
    sample1 = SampleSummary(id="sample1", epoch=1, input="test1", target="test target")
    sample2 = SampleSummary(id="sample2", epoch=1, input="test2", target="test target")
    db.start_sample(sample=sample1)
    db.start_sample(sample=sample2)

    events1: list[Event] = [InfoEvent(data="event1")]
    events2: list[Event] = [InfoEvent(data="event2")]

    db.log_events(id="sample1", epoch=1, events=events1)
    db.log_events(id="sample2", epoch=1, events=events2)

    # Test filtering by sample
    filtered_events = list(db.get_events(id="sample1", epoch=1))
    assert len(filtered_events) == 1
    assert filtered_events[0].event["data"] == "event1"

    # Test getting all events
    sample_1_events = list(db.get_events("sample1", 1))
    sample_2_events = list(db.get_events("sample2", 1))
    assert len(sample_1_events) == 1
    assert len(sample_2_events) == 1


def test_error_cases(db: SampleEventDatabase) -> None:
    """Test various error cases."""
    # Test logging events for non-existent sample
    with pytest.raises(IntegrityError):
        test_event: list[Event] = [InfoEvent(data={"type": "test"})]
        db.log_events(id="nonexistent", epoch=1, events=test_event)


def test_concurrent_samples(db: SampleEventDatabase) -> None:
    """Test handling multiple samples concurrently."""
    # Create multiple samples
    samples: list[SampleSummary] = [
        SampleSummary(id="sample1", epoch=1, input="test1", target="target"),
        SampleSummary(id="sample1", epoch=2, input="test1_v2", target="target"),
        SampleSummary(id="sample2", epoch=1, input="test2", target="target"),
    ]

    for sample in samples:
        db.start_sample(sample=sample)

    # Verify all samples were created
    stored_samples = list(db.get_samples())
    assert len(stored_samples) == 3

    # Verify we can get specific samples
    events: list[Event] = [InfoEvent(data="event1")]
    db.log_events(id="sample1", epoch=1, events=events)
    db.log_events(id="sample1", epoch=2, events=events)

    # Check events for specific epoch
    events_epoch_1 = list(db.get_events(id="sample1", epoch=1))
    assert len(events_epoch_1) == 1

    events_epoch_2 = list(db.get_events(id="sample1", epoch=2))
    assert len(events_epoch_2) == 1


def test_remove_samples(db: SampleEventDatabase) -> None:
    """Test removing samples and their associated events."""
    # Create multiple samples with events
    samples: list[SampleSummary] = [
        SampleSummary(id="sample1", epoch=1, input="test1", target="target"),
        SampleSummary(id="sample1", epoch=2, input="test1_v2", target="target"),
        SampleSummary(id="sample2", epoch=1, input="test2", target="target"),
    ]

    # Start all samples
    for sample in samples:
        db.start_sample(sample=sample)

    # Add events to each sample
    events: list[Event] = [InfoEvent(data="test_event")]
    for sample in samples:
        db.log_events(id=sample.id, epoch=sample.epoch, events=events)

    # Verify initial state
    initial_samples = list(db.get_samples())
    assert len(initial_samples) == 3
    assert all(list(db.get_events(s.id, s.epoch)) for s in samples)

    # Remove two of the samples
    samples_to_remove: list[tuple[str | int, int]] = [
        ("sample1", 1),
        ("sample2", 1),
    ]
    db.remove_samples(samples_to_remove)

    # Verify samples were removed
    remaining_samples = list(db.get_samples())
    assert len(remaining_samples) == 1
    assert remaining_samples[0].id == "sample1"
    assert remaining_samples[0].epoch == 2

    # Verify events were removed
    for sample_id, epoch in samples_to_remove:
        assert not list(db.get_events(sample_id, epoch))

    # Verify remaining sample still has its events
    remaining_events = list(db.get_events("sample1", 2))
    assert len(remaining_events) == 1

    # Test removing non-existent samples (should not raise an error)
    db.remove_samples([("nonexistent", 1), ("sample1", 999)])


def test_insert_attachments(db: SampleEventDatabase) -> None:
    """Test inserting attachments into the database."""
    # Create test attachments
    attachments = {"hash1": "content1", "hash2": "content2", "hash3": "content3"}

    # Insert attachments
    db.insert_attachments(attachments)

    # Verify attachments were stored
    stored = db.get_attachments(list(attachments.keys()))
    assert stored == attachments


def test_get_nonexistent_attachments(db: SampleEventDatabase) -> None:
    """Test retrieving non-existent attachments."""
    # Try to get attachments that don't exist
    hashes = ["nonexistent1", "nonexistent2"]
    result = db.get_attachments(hashes)

    # Should return None for non-existent hashes
    assert result == {"nonexistent1": None, "nonexistent2": None}


def test_insert_duplicate_attachments(db: SampleEventDatabase) -> None:
    """Test handling of duplicate attachment insertions."""
    # Initial insertion
    initial_attachments = {"hash1": "content1", "hash2": "content2"}
    db.insert_attachments(initial_attachments)

    # Try to insert same hash with different content
    duplicate_attachments = {"hash1": "different_content", "hash3": "content3"}
    db.insert_attachments(duplicate_attachments)

    # Verify original content was preserved for hash1
    # and new content was added for hash3
    stored = db.get_attachments(["hash1", "hash2", "hash3"])
    assert stored == {
        "hash1": "content1",  # Original content preserved
        "hash2": "content2",
        "hash3": "content3",  # New content added
    }


def test_get_mixed_existing_and_nonexistent_attachments(
    db: SampleEventDatabase,
) -> None:
    """Test retrieving a mix of existing and non-existent attachments."""
    # Insert some attachments
    attachments = {"existing1": "content1", "existing2": "content2"}
    db.insert_attachments(attachments)

    # Try to get both existing and non-existent attachments
    hashes = ["existing1", "nonexistent", "existing2"]
    result = db.get_attachments(hashes)

    # Should return content for existing and None for non-existent
    assert result == {
        "existing1": "content1",
        "nonexistent": None,
        "existing2": "content2",
    }


def test_empty_attachment_operations(db: SampleEventDatabase) -> None:
    """Test attachment operations with empty inputs."""
    # Test inserting empty dict
    db.insert_attachments({})

    # Test getting empty list of hashes
    result = db.get_attachments([])
    assert result == {}


def test_cleanup(db: SampleEventDatabase, sample: SampleSummary) -> None:
    """Test database cleanup."""
    # Create some data
    db.start_sample(sample=sample)

    # Verify file exists
    assert os.path.exists(db.db_path)

    # Cleanup
    db.cleanup()

    # Verify file is gone
    assert not os.path.exists(db.db_path)

    # Verify cleanup is idempotent
    db.cleanup()  # Should not raise any errors
