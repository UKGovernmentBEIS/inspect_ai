import tempfile
from pathlib import Path

import pytest

from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer.database import (
    SampleBufferDatabase,
    sync_to_filestore,
)
from inspect_ai.log._recorders.buffer.filestore import SampleBufferFilestore
from inspect_ai.log._recorders.buffer.types import Samples
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._transcript import InfoEvent


@pytest.fixture
def db_and_filestore():
    """Creates a real SampleBufferDatabase and a real SampleBufferFilestore in a temporary directory, then yields them for tests to use.

    After the test finishes, the entire directory is cleaned up automatically.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1) Create the database in tmpdir
        db_dir = Path(tmpdir)
        db_location = "testdb"  # Arbitrary name; used as the 'location' string
        db = SampleBufferDatabase(location=db_location, create=True, db_dir=db_dir)

        # 2) Create a filestore in a subdirectory
        filestore_dir = Path(tmpdir) / "filestore"
        filestore = SampleBufferFilestore(str(filestore_dir), create=True)

        yield (db, filestore)

        # No explicit cleanup needed; the TemporaryDirectory is removed afterward.


def test_sync_no_data(
    db_and_filestore: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """If the database has no samples, syncing should create an empty manifest (with no samples, no segments)."""
    db, filestore = db_and_filestore

    # 1) Ensure the DB has no samples
    samples = db.get_samples()
    assert isinstance(samples, Samples)
    assert samples is None or len(samples.samples) == 0

    # 2) Sync
    sync_to_filestore(db, filestore)

    # 3) Read manifest from filestore
    manifest = filestore.read_manifest()
    assert manifest is not None, "Even if no data, we expect a manifest object"
    assert len(manifest.samples) == 0, "No samples in the manifest"
    assert len(manifest.segments) == 0, "No segments created"


def test_sync_one_sample(
    db_and_filestore: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Create one sample with some events, sync, and verify that exactly one segment is created in the filestore, containing the new data."""
    db, filestore = db_and_filestore

    # 1) Start a sample in the DB
    sample = EvalSampleSummary(id="s1", epoch=1, input="Hello", target="World")
    db.start_sample(sample)

    # 2) Log a couple of events
    event1 = SampleEvent(id="s1", epoch=1, event=InfoEvent(data="first event"))
    event2 = SampleEvent(id="s1", epoch=1, event=InfoEvent(data="second event"))
    db.log_events([event1, event2])

    # 3) Sync to filestore
    sync_to_filestore(db, filestore)

    # 4) Read manifest -> should have 1 sample, 1 segment
    manifest = filestore.read_manifest()
    assert manifest is not None
    assert len(manifest.samples) == 1
    assert manifest.samples[0].summary.id == "s1"
    assert manifest.samples[0].summary.epoch == 1

    assert len(manifest.segments) == 1, "Should have one new segment"
    segment = manifest.segments[0]
    # last_event_id should be at least 2 (event1, event2)
    assert segment.last_event_id >= 2
    assert segment.last_attachment_id == 0

    # 5) Check that filestore returns the sample in get_samples
    fs_samples = filestore.get_samples()
    assert isinstance(fs_samples, Samples)
    assert len(fs_samples.samples) == 1
    assert fs_samples.samples[0].id == "s1"

    # 6) Check that get_sample_data returns the events
    sample_data = filestore.get_sample_data("s1", 1)
    assert sample_data is not None
    assert len(sample_data.events) == 2
    msgs = [ev.event["data"] for ev in sample_data.events]
    assert msgs == ["first event", "second event"]


def test_sync_multiple_samples(
    db_and_filestore: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Create multiple samples, each with events, sync once, and verify that they share a single new segment."""
    db, filestore = db_and_filestore

    # Create two samples
    s1 = EvalSampleSummary(id="A", epoch=1, input="inputA", target="targetA")
    s2 = EvalSampleSummary(id="B", epoch=1, input="inputB", target="targetB")
    db.start_sample(s1)
    db.start_sample(s2)

    event1 = SampleEvent(id="A", epoch=1, event=InfoEvent(data="A1"))
    event2 = SampleEvent(id="B", epoch=1, event=InfoEvent(data="B1"))
    db.log_events([event1, event2])

    # Sync
    sync_to_filestore(db, filestore)

    # Manifest => 2 samples, 1 segment
    manifest = filestore.read_manifest()
    assert manifest is not None
    assert len(manifest.samples) == 2
    assert len(manifest.segments) == 1

    # Each sample references that single segment
    seg_id = manifest.segments[0].id
    for sm in manifest.samples:
        assert seg_id in sm.segments

    # Filestore get_sample_data => each sample has its event
    data_a = filestore.get_sample_data("A", 1)
    data_b = filestore.get_sample_data("B", 1)
    assert data_a and data_b
    assert len(data_a.events) == 1
    assert len(data_b.events) == 1


def test_sync_removed_sample(
    db_and_filestore: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """If a sample is removed from the DB, it should be removed from the manifest after sync. Existing segments remain, but the sample won't appear in the manifest."""
    db, filestore = db_and_filestore

    # Create two samples
    s1 = EvalSampleSummary(id="keep", epoch=1, input="x", target="y")
    s2 = EvalSampleSummary(id="remove", epoch=1, input="xx", target="yy")
    db.start_sample(s1)
    db.start_sample(s2)

    db.log_events(
        [
            SampleEvent(id="keep", epoch=1, event=InfoEvent(data="keep1")),
            SampleEvent(id="remove", epoch=1, event=InfoEvent(data="remove1")),
        ]
    )

    # First sync
    sync_to_filestore(db, filestore)
    m1 = filestore.read_manifest()
    assert m1 and len(m1.samples) == 2

    # Remove s2 from DB
    db.remove_samples([("remove", 1)])

    # Second sync
    sync_to_filestore(db, filestore)
    m2 = filestore.read_manifest()
    assert m2 and len(m2.samples) == 1
    # Only 'keep' remains
    assert m2.samples[0].summary.id == "keep"


def test_sync_incremental(
    db_and_filestore: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    """Demonstrate incremental sync. First, create a sample and log events; sync. Then log more events and sync again, ensuring a second segment is created containing only the new events."""
    db, filestore = db_and_filestore

    s1 = EvalSampleSummary(id="inc", epoch=1, input="foo", target="bar")
    db.start_sample(s1)

    # First batch
    db.log_events(
        [
            SampleEvent(id="inc", epoch=1, event=InfoEvent(data="1")),
            SampleEvent(id="inc", epoch=1, event=InfoEvent(data="2")),
        ]
    )

    # First sync
    sync_to_filestore(db, filestore)
    m1 = filestore.read_manifest()
    assert m1 and len(m1.segments) == 1
    seg1 = m1.segments[0]
    assert seg1.last_event_id >= 2

    # Second batch
    db.log_events(
        [
            SampleEvent(id="inc", epoch=1, event=InfoEvent(data="3")),
            SampleEvent(id="inc", epoch=1, event=InfoEvent(data="4")),
        ]
    )

    # Second sync
    sync_to_filestore(db, filestore)
    m2 = filestore.read_manifest()
    assert m2 and len(m2.segments) == 2
    seg2 = m2.segments[-1]
    assert seg2.id > seg1.id
    assert seg2.last_event_id >= 4

    # Confirm filestore returns all 4 events
    sample_data = filestore.get_sample_data("inc", 1)
    assert sample_data is not None
