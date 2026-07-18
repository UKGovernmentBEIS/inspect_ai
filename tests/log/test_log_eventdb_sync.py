import hashlib
import tempfile
from pathlib import Path

import pytest

from inspect_ai.event._info import InfoEvent
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer import filestore as filestore_module
from inspect_ai.log._recorders.buffer.database import (
    SampleBufferDatabase,
    sync_to_filestore,
)
from inspect_ai.log._recorders.buffer.filestore import (
    Manifest,
    SampleBufferFilestore,
    SampleManifest,
    SampleSegment,
    Segment,
    sample_segment_id,
)
from inspect_ai.log._recorders.buffer.types import Samples
from inspect_ai.log._recorders.types import SampleEvent


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


def test_sync_sample_metadata_outside_manifest_summary(
    db_and_filestore: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    db, filestore = db_and_filestore
    initial = {"world": {f"cell-{i}": {"active": True} for i in range(80)}}
    final = {"world": {**initial["world"], "solver-added": {"active": False}}}
    summary = EvalSampleSummary(
        id="s1",
        epoch=1,
        input="Hello",
        target="World",
        metadata=initial,
    )

    db.start_sample(summary)
    db.complete_sample(summary, final)
    sync_to_filestore(db, filestore)
    final_manifest = filestore.read_manifest()
    assert final_manifest is not None
    assert final_manifest.samples[0].metadata_hash is not None
    assert final_manifest.samples[0].summary.metadata["world"] == (
        "Key removed from summary (> 1k)"
    )
    assert filestore.get_sample_metadata("s1", 1) == final


def test_sample_metadata_file_normalizes_sample_id(
    db_and_filestore: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    _, filestore = db_and_filestore

    assert filestore._sample_metadata_file(1, 1, "digest") == (
        filestore._sample_metadata_file("1", 1, "digest")
    )


@pytest.mark.parametrize("failure", ["hash_mismatch", "invalid_json"])
def test_read_sample_metadata_falls_back_on_invalid_sidecar(
    db_and_filestore: tuple[SampleBufferDatabase, SampleBufferFilestore],
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []

    def capture_warning(msg: object, *args: object, **_kwargs: object) -> None:
        warnings.append(str(msg) % args if args else str(msg))

    monkeypatch.setattr(filestore_module.logger, "warning", capture_warning)
    db, filestore = db_and_filestore
    metadata = {"world": {f"cell-{i}": {"active": True} for i in range(80)}}
    summary = EvalSampleSummary(
        id="s1", epoch=1, input="Hello", target="World", metadata=metadata
    )

    db.start_sample(summary)
    db.complete_sample(summary, metadata)
    sync_to_filestore(db, filestore)

    manifest = filestore.read_manifest()
    assert manifest is not None
    metadata_hash = manifest.samples[0].metadata_hash
    assert metadata_hash is not None
    if failure == "hash_mismatch":
        metadata_path = filestore._sample_metadata_file("s1", 1, metadata_hash)
        Path(metadata_path).write_bytes(b"{}")
    else:
        invalid_json = b"{"
        metadata_hash = hashlib.sha256(invalid_json).hexdigest()
        filestore.write_sample_metadata("s1", 1, metadata_hash, invalid_json)
        manifest.samples[0].metadata_hash = metadata_hash
        filestore.write_manifest(manifest)

    assert filestore.get_sample_metadata("s1", 1) is None
    assert any(
        "Unable to read sample metadata for id=s1 epoch=1" in warning
        for warning in warnings
    )


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
        assert seg_id in {sample_segment_id(segment) for segment in sm.segments}

    # Filestore get_sample_data => each sample has its event
    data_a = filestore.get_sample_data("A", 1)
    data_b = filestore.get_sample_data("B", 1)
    assert data_a and data_b
    assert len(data_a.events) == 1
    assert len(data_b.events) == 1


def test_pending_segments_use_per_sample_maxima(
    db_and_filestore: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    db, filestore = db_and_filestore

    db.start_sample(EvalSampleSummary(id="a", epoch=1, input="in", target="out"))
    db.start_sample(EvalSampleSummary(id="b", epoch=1, input="in", target="out"))
    db.log_events(
        [
            SampleEvent(id="a", epoch=1, event=InfoEvent(data="a-one")),
            SampleEvent(id="b", epoch=1, event=InfoEvent(data="b-one")),
            SampleEvent(id="b", epoch=1, event=InfoEvent(data="b-two")),
        ]
    )

    sync_to_filestore(db, filestore)
    manifest = filestore.read_manifest()

    assert manifest is not None
    assert len(manifest.segments) == 1
    assert manifest.segments[0].last_event_id == 3

    sample_a = next(s for s in manifest.samples if s.summary.id == "a")
    sample_b = next(s for s in manifest.samples if s.summary.id == "b")
    assert sample_a.segments == [
        SampleSegment(id=1, last_event_id=1, last_attachment_id=0)
    ]
    assert sample_b.segments == [
        SampleSegment(id=1, last_event_id=3, last_attachment_id=0)
    ]

    pending = filestore.get_pending_segments("a", 1, after_event_id=1)

    assert pending is not None
    assert pending.segments == []


def test_sync_continues_from_legacy_integer_segments(
    db_and_filestore: tuple[SampleBufferDatabase, SampleBufferFilestore],
) -> None:
    db, filestore = db_and_filestore

    db.start_sample(EvalSampleSummary(id="a", epoch=1, input="in", target="out"))
    db.log_events([SampleEvent(id="a", epoch=1, event=InfoEvent(data="old"))])

    legacy_manifest = Manifest(
        samples=[
            SampleManifest(
                summary=EvalSampleSummary(id="a", epoch=1, input="in", target="out"),
                segments=[1],
            )
        ],
        segments=[Segment(id=1, last_event_id=1, last_attachment_id=0)],
    )
    filestore.write_manifest(legacy_manifest)

    db.log_events([SampleEvent(id="a", epoch=1, event=InfoEvent(data="new"))])
    sync_to_filestore(db, filestore)
    manifest = filestore.read_manifest()

    assert manifest is not None
    sample = manifest.samples[0]
    assert sample.segments == [
        1,
        SampleSegment(id=2, last_event_id=2, last_attachment_id=0),
    ]
    assert [
        event.event["data"] for event in filestore.read_segment_data(2, "a", 1).events
    ] == ["new"]


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
