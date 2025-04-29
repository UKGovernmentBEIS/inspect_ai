import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Iterator, cast

import pytest

from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.database import sync_to_filestore
from inspect_ai.log._recorders.buffer.filestore import SampleBufferFilestore
from inspect_ai.log._recorders.buffer.types import Samples
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._transcript import Event, InfoEvent
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser


@pytest.fixture
def db() -> Generator[SampleBufferDatabase, None, None]:
    """Fixture to create and cleanup a test database."""
    with tempfile.TemporaryDirectory() as db_dir:
        test_db = SampleBufferDatabase(location="test_location", db_dir=Path(db_dir))
        yield test_db
        test_db.cleanup()


@pytest.fixture
def sample() -> Generator[EvalSampleSummary, None, None]:
    yield EvalSampleSummary(
        id="sample1", epoch=1, input="test input", target="test target"
    )


def get_samples(db: SampleBufferDatabase) -> Samples:
    samples = db.get_samples()
    assert isinstance(samples, Samples)
    return samples


def test_database_initialization(db: SampleBufferDatabase) -> None:
    """Test that the database is properly initialized."""
    assert os.path.exists(db.db_path)
    assert bool(re.search(r"test_location\.\d+\.db$", db.db_path.as_posix()))


def test_start_sample(db: SampleBufferDatabase, sample: EvalSampleSummary) -> None:
    """Test starting a new sample."""
    db.start_sample(sample=sample)

    # Verify the sample was created
    samples = get_samples(db).samples
    assert len(samples) == 1
    assert samples[0] == sample


def test_log_events(db: SampleBufferDatabase, sample: EvalSampleSummary) -> None:
    """Test logging events for a sample."""
    # First create a sample
    db.start_sample(sample=sample)

    # Log some events
    events: list[Event] = [InfoEvent(data="event1"), InfoEvent(data="event2")]
    db.log_events([SampleEvent(id="sample1", epoch=1, event=event) for event in events])

    # Verify events were logged
    with db._get_connection() as conn:
        logged_events = list(db._get_events(conn, id="sample1", epoch=1))
    assert len(logged_events) == 2


def test_complete_sample(db: SampleBufferDatabase, sample: EvalSampleSummary) -> None:
    """Test completing a sample with a summary."""
    # Create sample
    db.start_sample(sample=sample)

    # Complete sample
    summary = EvalSampleSummary(
        id=sample.id, epoch=sample.epoch, input=sample.input, target=sample.target
    )
    db.complete_sample(summary=summary)

    # Verify summary was added
    samples = get_samples(db)
    assert len(samples.samples) == 1
    assert samples.samples[0] == summary


def test_get_events_with_filters(db: SampleBufferDatabase) -> None:
    """Test getting events with various filters."""
    # Create two samples with events
    sample1 = EvalSampleSummary(
        id="sample1", epoch=1, input="test1", target="test target"
    )
    sample2 = EvalSampleSummary(
        id="sample2", epoch=1, input="test2", target="test target"
    )
    db.start_sample(sample=sample1)
    db.start_sample(sample=sample2)

    event1 = InfoEvent(data="event1")
    event2 = InfoEvent(data="event2")

    db.log_events(
        [
            SampleEvent(id="sample1", epoch=1, event=event1),
            SampleEvent(id="sample2", epoch=1, event=event2),
        ]
    )

    # Test filtering by sample
    with db._get_connection() as conn:
        filtered_events = list(db._get_events(conn, id="sample1", epoch=1))
        assert len(filtered_events) == 1
        assert filtered_events[0].event["data"] == "event1"

        # Test getting all events
        sample_1_events = list(db._get_events(conn, "sample1", 1))
        sample_2_events = list(db._get_events(conn, "sample2", 1))
        assert len(sample_1_events) == 1
        assert len(sample_2_events) == 1


def test_concurrent_samples(db: SampleBufferDatabase) -> None:
    """Test handling multiple samples concurrently."""
    # Create multiple samples
    samples: list[EvalSampleSummary] = [
        EvalSampleSummary(id="sample1", epoch=1, input="test1", target="target"),
        EvalSampleSummary(id="sample1", epoch=2, input="test1_v2", target="target"),
        EvalSampleSummary(id="sample2", epoch=1, input="test2", target="target"),
    ]

    for sample in samples:
        db.start_sample(sample=sample)

    # Verify all samples were created
    stored_samples = get_samples(db)
    assert len(stored_samples.samples) == 3

    # Verify we can get specific samples
    event = InfoEvent(data="event1")
    db.log_events(
        [
            SampleEvent(id="sample1", epoch=1, event=event),
            SampleEvent(id="sample1", epoch=2, event=event),
        ]
    )

    # Check events for specific epoch
    with db._get_connection() as conn:
        events_epoch_1 = list(db._get_events(conn, id="sample1", epoch=1))
        assert len(events_epoch_1) == 1

        events_epoch_2 = list(db._get_events(conn, id="sample1", epoch=2))
        assert len(events_epoch_2) == 1


def test_remove_samples(db: SampleBufferDatabase) -> None:
    """Test removing samples and their associated events."""
    # Create multiple samples with events
    samples: list[EvalSampleSummary] = [
        EvalSampleSummary(id="sample1", epoch=1, input="test1", target="target"),
        EvalSampleSummary(id="sample1", epoch=2, input="test1_v2", target="target"),
        EvalSampleSummary(id="sample2", epoch=1, input="test2", target="target"),
    ]

    # Start all samples
    for sample in samples:
        db.start_sample(sample=sample)

    # Add events to each sample
    event = InfoEvent(data="test_event")
    for sample in samples:
        db.log_events([SampleEvent(id=sample.id, epoch=sample.epoch, event=event)])

    # Verify initial state
    initial_samples = get_samples(db).samples
    assert len(initial_samples) == 3
    with db._get_connection() as conn:
        assert all(list(db._get_events(conn, s.id, s.epoch)) for s in samples)

    # Remove two of the samples
    samples_to_remove: list[tuple[str | int, int]] = [
        ("sample1", 1),
        ("sample2", 1),
    ]
    db.remove_samples(samples_to_remove)

    # Verify samples were removed
    remaining_samples = get_samples(db)
    assert len(remaining_samples.samples) == 1
    assert remaining_samples.samples[0].id == "sample1"
    assert remaining_samples.samples[0].epoch == 2

    # Verify events were removed
    with db._get_connection() as conn:
        for sample_id, epoch in samples_to_remove:
            assert not list(db._get_events(conn, sample_id, epoch))

        # Verify remaining sample still has its events
        remaining_events = list(db._get_events(conn, "sample1", 2))
        assert len(remaining_events) == 1

    # Test removing non-existent samples (should not raise an error)
    db.remove_samples([("nonexistent", 1), ("sample1", 999)])


def test_insert_attachments(db: SampleBufferDatabase) -> None:
    """Test inserting attachments into the database."""
    # Create test attachments
    attachments = {"hash1": "content1", "hash2": "content2", "hash3": "content3"}

    # Insert attachments
    with db._get_connection() as conn:
        db._insert_attachments(conn, 1, 1, attachments)

    # Verify attachment api
    with db._get_connection() as conn:
        attachments_info = list(db._get_attachments(conn, 1, 1))
        assert len(attachments_info) == len(attachments)
        for i in range(0, len(attachments_info)):
            assert attachments_info[i].hash == list(attachments.keys())[i]
            assert attachments_info[i].content == list(attachments.values())[i]

        attachment_info = list(db._get_attachments(conn, 1, 1, 2))[0]
        assert attachment_info.hash == list(attachments.keys())[2]
        assert attachment_info.content == list(attachments.values())[2]


def test_insert_duplicate_attachments(db: SampleBufferDatabase) -> None:
    """Test handling of duplicate attachment insertions."""
    # Initial insertion
    initial_attachments = {"hash1": "content1", "hash2": "content2"}
    with db._get_connection() as conn:
        db._insert_attachments(conn, 1, 1, initial_attachments)

        # Try to insert same hash with different content
        duplicate_attachments = {"hash1": "different_content", "hash3": "content3"}
        db._insert_attachments(conn, 1, 1, duplicate_attachments)

        # Verify original content was preserved for hash1
        # and new content was added for hash3
        stored = list(db._get_attachments(conn, 1, 1))
        assert stored[0].content == "content1"  # Original content preserved
        assert stored[1].content == "content2"
        assert stored[2].content == "content3"  # New content added


def test_large_input_attachment_handling(db: SampleBufferDatabase) -> None:
    """Test that large inputs are automatically converted to attachments."""
    # Create a sample with input larger than 100 characters
    large_input = ChatMessageUser(content="x" * 150)
    sample = EvalSampleSummary(
        id="large_sample",
        epoch=1,
        input=[large_input],
        target="test target",
    )

    # Start the sample
    db.start_sample(sample=sample)

    # Retrieve the stored sample
    with db._get_connection() as conn:
        stored_samples = list(db._get_samples(conn, resolve_attachments=True))
    assert len(stored_samples) == 1

    # Verify the stored input matches the original large input
    retrieved_sample = stored_samples[0]
    assert retrieved_sample
    assert isinstance(retrieved_sample.input, list)
    assert retrieved_sample.input == [large_input]

    # Verify an attachment was created in the database
    # Get raw database content to verify attachment placeholder
    with db._get_connection() as conn:
        cursor = conn.execute(
            "SELECT data FROM samples WHERE id = ? AND epoch = ?",
            ("large_sample", 1),
        )
        raw_input: list[dict[str, Any]] = json.loads(cursor.fetchone()[0])["input"]

        # Verify the raw input is a placeholder (should start with "attachment:")
        raw_input_text = raw_input[0]["content"]
        assert raw_input_text.startswith("attachment:")

        # Get the attachment hash from the placeholder
        attachment_hash = raw_input_text.split("://")[1]

        # Verify the attachment exists and contains the original content
        cursor = conn.execute(
            "SELECT content FROM attachments WHERE hash = ?", (attachment_hash,)
        )
        stored_content = cursor.fetchone()[0]
        assert stored_content == large_input.text


def test_large_event_attachment_handling(db: SampleBufferDatabase) -> None:
    """Test that events with large data fields are automatically converted to attachments."""
    # Create a normal sample
    sample = EvalSampleSummary(
        id="event_test", epoch=1, input="test input", target="test target"
    )
    db.start_sample(sample=sample)

    # Create an event with large data
    large_data = "x" * 150  # Data that exceeds the 100 char limit
    event = InfoEvent(data=large_data)

    # Log the event
    db.log_events([SampleEvent(id="event_test", epoch=1, event=event)])

    # Retrieve the stored events
    with db._get_connection() as conn:
        stored_events = list(
            db._get_events(conn, "event_test", 1, resolve_attachments=True)
        )
    assert len(stored_events) == 1

    # Verify the retrieved event data matches the original
    assert stored_events[0].event["data"] == large_data

    # Verify attachment was created
    with db._get_connection() as conn:
        cursor = conn.execute(
            "SELECT data FROM events WHERE sample_id = ? AND sample_epoch = ?",
            ("event_test", 1),
        )
        raw_event_data = cursor.fetchone()[0]

        # Parse the JSON event data and check the data field
        import json

        event_dict = json.loads(raw_event_data)
        assert event_dict["data"].startswith("attachment:")

        # Get the attachment hash
        attachment_hash = event_dict["data"].split("://")[1]

        # Verify the attachment exists and contains the original content
        cursor = conn.execute(
            "SELECT content FROM attachments WHERE hash = ?", (attachment_hash,)
        )
        stored_content = cursor.fetchone()[0]
        assert stored_content == large_data


def test_multiple_attachments_same_content(db: SampleBufferDatabase) -> None:
    """Test that identical large content creates only one attachment."""
    large_input: list[ChatMessage] = [ChatMessageUser(content="x" * 150)]

    # Create two samples with the same large input
    samples = [
        EvalSampleSummary(id=f"sample{i}", epoch=1, input=large_input, target="test")
        for i in range(2)
    ]

    for sample in samples:
        db.start_sample(sample=sample)

    # Verify both samples are stored correctly
    with db._get_connection() as conn:
        stored_samples = list(db._get_samples(conn, resolve_attachments=True))
    assert len(stored_samples) == 2
    assert all(cast(list[ChatMessage], s.input) == large_input for s in stored_samples)

    # Verify only one attachment was created
    with db._get_connection() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM attachments")
        attachment_count = cursor.fetchone()[0]
        assert attachment_count == 1


def test_mixed_content_sizes(db: SampleBufferDatabase) -> None:
    """Test handling of mixed regular and large content in the same sample."""
    large_input: list[ChatMessage] = [ChatMessageUser(content="x" * 150)]
    small_data = "small"
    large_data = "y" * 150

    # Create sample with large input
    sample = EvalSampleSummary(
        id="mixed_test", epoch=1, input=large_input, target="test target"
    )
    db.start_sample(sample=sample)

    # Log both small and large events
    events: list[Event] = [InfoEvent(data=small_data), InfoEvent(data=large_data)]
    db.log_events(
        [SampleEvent(id="mixed_test", epoch=1, event=event) for event in events]
    )

    # Verify everything is stored and retrieved correctly
    with db._get_connection() as conn:
        stored_samples = list(db._get_samples(conn, resolve_attachments=True))
        assert stored_samples[0]
        assert stored_samples[0].input == large_input

        stored_events = list(
            db._get_events(conn, "mixed_test", 1, resolve_attachments=True)
        )
        assert len(stored_events) == 2
        assert stored_events[0].event["data"] == small_data
        assert stored_events[1].event["data"] == large_data

        # Verify attachment count
        cursor = conn.execute("SELECT COUNT(*) FROM attachments")
        attachment_count = cursor.fetchone()[0]
        assert attachment_count == 2  # One for input, one for large event


def test_version_increments_on_write_operations(db: SampleBufferDatabase):
    """Test that write operations increment the version."""
    with db._get_connection() as conn:
        task_data = db._get_task_data(conn)

    # Test write operation
    sample = EvalSampleSummary(id="test1", epoch=1, input="foo", target="bar")
    db.start_sample(sample)

    with db._get_connection() as conn:
        after_write = db._get_task_data(conn)

    assert after_write.version == task_data.version + 1


def test_version_unchanged_on_read_operations(
    db: SampleBufferDatabase, sample: EvalSampleSummary
):
    """Test that read operations don't change the version."""
    # First add a sample so we have something to read
    db.start_sample(sample)

    with db._get_connection() as conn:
        initial_version = db._get_task_data(conn)

    # Perform read operations
    get_samples(db)
    db.get_sample_data(str(sample.id), sample.epoch)

    with db._get_connection() as conn:
        after_reads = db._get_task_data(conn)

    assert after_reads == initial_version


def test_version_in_samples_etag(db: SampleBufferDatabase):
    """Test that samples etag matches current version."""
    with db._get_connection() as conn:
        task_data = db._get_task_data(conn)

    samples = get_samples(db)
    assert samples.etag == str(task_data.version)


def test_cleanup(db: SampleBufferDatabase, sample: EvalSampleSummary) -> None:
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


def test_running_tasks():
    with tempfile.TemporaryDirectory() as log_dir:

        @contextmanager
        def test_sample_buffers(
            name: str,
        ) -> Iterator[tuple[SampleBufferDatabase, SampleBufferFilestore]]:
            # create buffers
            test_log = (Path(log_dir) / f"{name}.eval").as_posix()
            test_db = SampleBufferDatabase(test_log)
            test_fs = SampleBufferFilestore(test_log)

            try:
                # some test data
                s1 = EvalSampleSummary(id="inc", epoch=1, input="foo", target="bar")
                test_db.start_sample(s1)

                # First batch
                test_db.log_events(
                    [
                        SampleEvent(id="inc", epoch=1, event=InfoEvent(data="1")),
                        SampleEvent(id="inc", epoch=1, event=InfoEvent(data="2")),
                    ]
                )

                # write to filestore
                sync_to_filestore(test_db, test_fs)

                yield test_db, test_fs
            finally:
                test_db.cleanup()
                test_fs.cleanup()

        with test_sample_buffers("test1"), test_sample_buffers("test2"):
            log_uri = Path(log_dir).absolute().as_uri()
            assert len(SampleBufferDatabase.running_tasks(log_uri)) == 2
            assert len(SampleBufferFilestore.running_tasks(log_dir)) == 2
