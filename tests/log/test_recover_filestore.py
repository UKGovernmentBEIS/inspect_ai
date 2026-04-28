"""Tests for filestore-based eval log recovery."""

import json
import os
import tempfile
from datetime import datetime, timezone
from zipfile import ZipFile

import pytest
from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._sample_limit import SampleLimitEvent
from inspect_ai.log._condense import ATTACHMENT_PROTOCOL
from inspect_ai.log._file import read_eval_log
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalPlan,
    EvalSample,
    EvalSampleSummary,
    EvalSpec,
)
from inspect_ai.log._recorders.buffer.filestore import (
    Manifest,
    SampleBufferFilestore,
    SampleManifest,
    Segment,
    segment_file_name,
    segment_name,
)
from inspect_ai.log._recorders.buffer.types import (
    AttachmentData,
    EventData,
    SampleData,
)
from inspect_ai.log._recorders.eval import LogStart
from inspect_ai.log._recover import (
    recover_eval_log_async,
    recoverable_eval_logs,
)
from inspect_ai.log._recover._buffer import (
    BufferRecoveryData,
    read_buffer_recovery_data,
)
from inspect_ai.model._chat_message import (
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


def _make_model_event_dict(content: str) -> dict:
    """Create a ModelEvent and return its JSON-serializable dict."""
    event = ModelEvent(
        model="mockllm/model",
        input=[ChatMessageUser(content="test input")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content(model="mockllm/model", content=content),
    )
    return to_jsonable_python(event, exclude_none=True)


def _make_summary(
    id: str | int = "sample1", epoch: int = 1, completed: bool = False
) -> EvalSampleSummary:
    return EvalSampleSummary(
        id=id,
        epoch=epoch,
        input=f"input {id}",
        target=f"target {id}",
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat() if completed else None,
    )


def _write_segment_zip(
    dir_path: str,
    segment_id: int,
    sample_id: str | int,
    epoch: int,
    events: list[dict],
    attachments: list | None = None,
) -> None:
    """Write a segment ZIP file with the given events."""
    sample_data = SampleData(
        events=[
            EventData(
                id=i + 1,
                event_id=f"evt-{segment_id}-{i}",
                sample_id=str(sample_id),
                epoch=epoch,
                event=e,
            )
            for i, e in enumerate(events)
        ],
        attachments=attachments or [],
    )
    zip_path = os.path.join(dir_path, segment_name(segment_id))
    with ZipFile(zip_path, "w") as zf:
        zf.writestr(
            segment_file_name(sample_id, epoch),
            json.dumps(to_jsonable_python(sample_data, exclude_none=True)),
        )


def _create_filestore_fixture(
    temp_dir: str,
    num_segments: int = 3,
    sample_id: str = "sample1",
    epoch: int = 1,
    completed: bool = False,
) -> tuple[str, Manifest]:
    """Create a .eval file path and .buffer directory with manifest + segments.

    Returns (eval_path, manifest).
    """
    eval_path = os.path.join(temp_dir, "test.eval")

    # Create .buffer directory structure
    buffer_dir = os.path.join(temp_dir, ".buffer", "test")
    os.makedirs(buffer_dir, exist_ok=True)

    # Write segments
    segments = []
    for i in range(1, num_segments + 1):
        event_dict = _make_model_event_dict(f"response from segment {i}")
        _write_segment_zip(buffer_dir, i, sample_id, epoch, [event_dict])
        segments.append(Segment(id=i, last_event_id=i, last_attachment_id=0))

    # Write manifest
    summary = _make_summary(id=sample_id, epoch=epoch, completed=completed)
    manifest = Manifest(
        samples=[SampleManifest(summary=summary, segments=[s.id for s in segments])],
        segments=segments,
    )
    manifest_path = os.path.join(buffer_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        f.write(manifest.model_dump_json())

    # Write .keep file (created by filestore constructor)
    with open(os.path.join(buffer_dir, ".keep"), "w") as f:
        pass

    return eval_path, manifest


def test_iter_sample_segments_reads_all() -> None:
    """iter_sample_segments yields all segments for a sample."""
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path, manifest = _create_filestore_fixture(temp_dir, num_segments=3)

        filestore = SampleBufferFilestore(eval_path, create=False)
        results = list(filestore.iter_sample_segments("sample1", 1, manifest))

        assert len(results) == 3
        for seg_id, data in results:
            assert isinstance(data, SampleData)
            assert len(data.events) == 1


def test_iter_sample_segments_yields_in_id_order() -> None:
    """iter_sample_segments yields segments sorted by id regardless of manifest order.

    Pool dedup and MessageAccumulator depend on chronological order; the
    manifest's segment list is not guaranteed to be sorted.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path, manifest = _create_filestore_fixture(temp_dir, num_segments=4)

        # Scramble manifest segment order
        scrambled = Manifest(
            samples=manifest.samples,
            segments=[manifest.segments[i] for i in [2, 0, 3, 1]],
        )

        filestore = SampleBufferFilestore(eval_path, create=False)
        results = list(filestore.iter_sample_segments("sample1", 1, scrambled))
        seg_ids = [seg_id for seg_id, _ in results]
        assert seg_ids == sorted(seg_ids)


def test_iter_sample_segments_skips_missing() -> None:
    """iter_sample_segments skips missing segments with a warning."""
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path, manifest = _create_filestore_fixture(temp_dir, num_segments=3)

        # Delete segment 2
        buffer_dir = os.path.join(temp_dir, ".buffer", "test")
        os.remove(os.path.join(buffer_dir, segment_name(2)))

        filestore = SampleBufferFilestore(eval_path, create=False)
        results = list(filestore.iter_sample_segments("sample1", 1, manifest))

        # Should get 2 segments (1 and 3), skipping missing segment 2
        assert len(results) == 2
        seg_ids = [seg_id for seg_id, _ in results]
        assert 1 in seg_ids
        assert 3 in seg_ids
        assert 2 not in seg_ids


def test_iter_sample_segments_skips_corrupt() -> None:
    """iter_sample_segments skips corrupt segments with a warning."""
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path, manifest = _create_filestore_fixture(temp_dir, num_segments=3)

        # Corrupt segment 2
        buffer_dir = os.path.join(temp_dir, ".buffer", "test")
        with open(os.path.join(buffer_dir, segment_name(2)), "wb") as f:
            f.write(b"not a zip file")

        filestore = SampleBufferFilestore(eval_path, create=False)
        results = list(filestore.iter_sample_segments("sample1", 1, manifest))

        assert len(results) == 2
        seg_ids = [seg_id for seg_id, _ in results]
        assert 2 not in seg_ids


def test_filestore_fallback_when_no_db() -> None:
    """read_buffer_recovery_data falls back to filestore when no SQLite DB exists."""
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path, _ = _create_filestore_fixture(
            temp_dir, num_segments=2, completed=True
        )
        db_dir = os.path.join(temp_dir, "empty_db_dir")

        recovery = read_buffer_recovery_data(eval_path, db_dir=db_dir)

        assert recovery is not None
        assert isinstance(recovery, BufferRecoveryData)
        assert len(recovery.completed) == 1
        assert len(recovery.in_progress) == 0
        assert recovery.buffer is not None


def test_filestore_fallback_in_progress_sample() -> None:
    """Filestore fallback correctly classifies in-progress samples."""
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path, _ = _create_filestore_fixture(
            temp_dir, num_segments=2, completed=False
        )
        db_dir = os.path.join(temp_dir, "empty_db_dir")

        recovery = read_buffer_recovery_data(eval_path, db_dir=db_dir)

        assert recovery is not None
        assert len(recovery.completed) == 0
        assert len(recovery.in_progress) == 1


def test_filestore_fallback_no_manifest() -> None:
    """Returns None when neither DB nor filestore manifest exists."""
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path = os.path.join(temp_dir, "test.eval")
        db_dir = os.path.join(temp_dir, "empty_db_dir")

        recovery = read_buffer_recovery_data(eval_path, db_dir=db_dir)
        assert recovery is None


def _write_crashed_eval(
    path: str,
    task: str = "test_task",
    sandbox: SandboxEnvironmentSpec | None = None,
) -> None:
    """Write a minimal crashed .eval file (no header.json)."""
    eval_spec = EvalSpec(
        created=datetime.now(timezone.utc).isoformat(),
        task=task,
        model="mockllm/model",
        dataset=EvalDataset(name="test", samples=1),
        config=EvalConfig(),
        sandbox=sandbox,
    )
    plan = EvalPlan()
    log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)
    with ZipFile(path, "w") as zf:
        zf.writestr(
            "_journal/start.json",
            json.dumps(to_jsonable_python(log_start, exclude_none=True)),
        )


async def test_recover_from_filestore_end_to_end() -> None:
    """Full recovery using filestore segments when no SQLite DB exists."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path, _ = _create_filestore_fixture(
                temp_dir, num_segments=3, completed=False
            )
            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            log = await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            assert log.status == "error"
            assert log.samples is not None
            assert len(log.samples) == 1

            # Verify the recovered sample has messages
            sample = log.samples[0]
            assert sample.id == "sample1"

            # Verify it can be read back
            read_log = read_eval_log(output_path)
            assert read_log.samples is not None
            assert len(read_log.samples) == 1


async def test_recover_from_filestore_with_missing_segment() -> None:
    """Recovery continues with best-effort when a segment is missing."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path, _ = _create_filestore_fixture(
                temp_dir, num_segments=3, completed=False
            )
            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            # Delete segment 2
            buffer_dir = os.path.join(temp_dir, ".buffer", "test")
            os.remove(os.path.join(buffer_dir, segment_name(2)))

            log = await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            # Recovery should succeed with remaining segments
            assert log.status == "error"
            assert log.samples is not None
            assert len(log.samples) == 1


def test_db_takes_priority_over_filestore() -> None:
    """When both SQLite DB and filestore exist, SQLite is used."""
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path, _ = _create_filestore_fixture(
            temp_dir, num_segments=2, completed=True
        )
        db_dir = os.path.join(temp_dir, "bufferdb")

        # Also create a buffer DB (from test_recover_buffer.py pattern)
        from pathlib import Path

        from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
        from inspect_ai.log._recorders.types import SampleEvent

        buffer = SampleBufferDatabase(eval_path, create=True, db_dir=Path(db_dir))
        started = EvalSampleSummary(
            id=99,
            epoch=1,
            input="db input",
            target="db target",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        buffer.start_sample(started)
        event = ModelEvent(
            model="mockllm/model",
            input=[ChatMessageUser(content="test")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_content(model="mockllm/model", content="db output"),
        )
        buffer.log_events([SampleEvent(id=99, epoch=1, event=event)])
        # Rename to dead PID
        old_path = buffer.db_path
        new_path = old_path.parent / old_path.name.replace(
            f".{os.getpid()}.", ".99999999."
        )
        old_path.rename(new_path)
        buffer.db_path = new_path

        recovery = read_buffer_recovery_data(eval_path, db_dir=db_dir)

        assert recovery is not None
        # Should have only the DB sample (id=99), not the filestore sample (id=sample1)
        all_samples = recovery.completed + recovery.in_progress
        sample_ids = [s.id for s in all_samples]
        assert sample_ids == [99]


async def test_recover_no_events_flag() -> None:
    """Recovery with no_events=True produces samples without event transcript."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path, _ = _create_filestore_fixture(
                temp_dir, num_segments=2, completed=False
            )
            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            log = await recover_eval_log_async(
                eval_path,
                output=output_path,
                cleanup=False,
                _db_dir=db_dir,
                no_events=True,
            )

            assert log.samples is not None
            assert len(log.samples) == 1
            sample = log.samples[0]
            # Messages should be present
            assert len(sample.messages) > 0
            # Events should be empty
            assert sample.events == []


def test_recoverable_eval_logs_with_filestore() -> None:
    """recoverable_eval_logs discovers filestore-backed crashed logs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path, _ = _create_filestore_fixture(
            temp_dir, num_segments=2, completed=False
        )
        _write_crashed_eval(eval_path)
        db_dir = os.path.join(temp_dir, "empty_db_dir")

        result = recoverable_eval_logs(log_dir=temp_dir, _db_dir=db_dir)

        assert len(result) == 1
        assert result[0].source == "filestore"
        assert result[0].in_progress_samples == 1


async def test_recover_filestore_cleanup() -> None:
    """Verify .buffer/ directory is removed after recovery by default."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path, _ = _create_filestore_fixture(
                temp_dir, num_segments=2, completed=False
            )
            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            buffer_dir = os.path.join(temp_dir, ".buffer", "test")
            assert os.path.exists(buffer_dir)

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=True, _db_dir=db_dir
            )

            assert not os.path.exists(buffer_dir)


async def test_recover_filestore_no_cleanup() -> None:
    """Verify .buffer/ directory preserved with cleanup=False."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path, _ = _create_filestore_fixture(
                temp_dir, num_segments=2, completed=False
            )
            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            buffer_dir = os.path.join(temp_dir, ".buffer", "test")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            assert os.path.exists(buffer_dir)


def _create_multi_sample_fixture(temp_dir: str) -> tuple[str, Manifest]:
    """Create a filestore fixture with multiple samples."""
    eval_path = os.path.join(temp_dir, "test.eval")
    buffer_dir = os.path.join(temp_dir, ".buffer", "test")
    os.makedirs(buffer_dir, exist_ok=True)

    # Sample 1: completed, 2 segments
    # Sample 2: in-progress, 1 segment
    segments = []

    # Segment 1: sample1 data
    event1 = _make_model_event_dict("answer for sample1 seg1")
    _write_segment_zip(buffer_dir, 1, "s1", 1, [event1])
    segments.append(Segment(id=1, last_event_id=1, last_attachment_id=0))

    # Segment 2: sample1 data
    event2 = _make_model_event_dict("answer for sample1 seg2")
    _write_segment_zip(buffer_dir, 2, "s1", 1, [event2])
    segments.append(Segment(id=2, last_event_id=2, last_attachment_id=0))

    # Segment 3: sample2 data
    event3 = _make_model_event_dict("partial answer for sample2")
    _write_segment_zip(buffer_dir, 3, "s2", 1, [event3])
    segments.append(Segment(id=3, last_event_id=1, last_attachment_id=0))

    summary1 = _make_summary(id="s1", epoch=1, completed=True)
    summary2 = _make_summary(id="s2", epoch=1, completed=False)

    manifest = Manifest(
        samples=[
            SampleManifest(summary=summary1, segments=[1, 2]),
            SampleManifest(summary=summary2, segments=[3]),
        ],
        segments=segments,
    )

    with open(os.path.join(buffer_dir, "manifest.json"), "w") as f:
        f.write(manifest.model_dump_json())
    with open(os.path.join(buffer_dir, ".keep"), "w") as f:
        pass

    return eval_path, manifest


async def test_recover_multi_sample() -> None:
    """Recovery with multiple samples, some completed and some in-progress."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path, _ = _create_multi_sample_fixture(temp_dir)

            eval_spec = EvalSpec(
                created=datetime.now(timezone.utc).isoformat(),
                task="test_task",
                model="mockllm/model",
                dataset=EvalDataset(name="test", samples=2),
                config=EvalConfig(),
            )
            plan = EvalPlan()
            log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)
            with ZipFile(eval_path, "w") as zf:
                zf.writestr(
                    "_journal/start.json",
                    json.dumps(to_jsonable_python(log_start, exclude_none=True)),
                )

            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            log = await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            assert log.samples is not None
            assert len(log.samples) == 2

            sample_ids = {s.id for s in log.samples}
            assert "s1" in sample_ids
            assert "s2" in sample_ids

            # s2 should have a cancellation error (in-progress)
            s2 = next(s for s in log.samples if s.id == "s2")
            assert s2.error is not None
            assert "CancelledError" in s2.error.message

            # s1 should not have a cancellation error (completed)
            s1 = next(s for s in log.samples if s.id == "s1")
            assert s1.error is None


def test_filestore_fallback_empty_manifest() -> None:
    """Filestore with empty manifest (no samples) returns empty recovery data."""
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path = os.path.join(temp_dir, "test.eval")
        buffer_dir = os.path.join(temp_dir, ".buffer", "test")
        os.makedirs(buffer_dir, exist_ok=True)

        manifest = Manifest(samples=[], segments=[])
        with open(os.path.join(buffer_dir, "manifest.json"), "w") as f:
            f.write(manifest.model_dump_json())
        with open(os.path.join(buffer_dir, ".keep"), "w") as f:
            pass

        db_dir = os.path.join(temp_dir, "empty_db_dir")
        recovery = read_buffer_recovery_data(eval_path, db_dir=db_dir)

        assert recovery is not None
        assert len(recovery.completed) == 0
        assert len(recovery.in_progress) == 0


async def test_streaming_recovery_has_events_data() -> None:
    """Streaming recovery produces condensed events with events_data pools.

    The on-disk sample JSON contains events_data with message/call pools
    and condensed events with input_refs. On read, resolve_sample_events_data
    expands the refs and sets events_data to None, so we verify that
    the resolved events have full input lists.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create fixture with multiple segments so pool dedup has work to do.
            # Each segment has a ModelEvent with the same user input message,
            # so the message pool should contain that message once.
            eval_path, _ = _create_filestore_fixture(
                temp_dir, num_segments=3, completed=True
            )
            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            # Read the raw sample JSON from the ZIP to verify events_data is present
            with ZipFile(output_path, "r") as zf:
                sample_names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("samples/") and n.endswith(".json")
                ]
                assert len(sample_names) == 1
                raw = json.loads(zf.read(sample_names[0]))

            assert "events_data" in raw
            assert raw["events_data"] is not None
            assert len(raw["events_data"]["messages"]) > 0

            # Verify condensed events have input_refs in the raw JSON
            model_events_raw = [e for e in raw["events"] if e.get("event") == "model"]
            assert len(model_events_raw) == 3
            for me in model_events_raw:
                assert "input_refs" in me
                assert me["input"] == []

            # Verify summaries.json is populated (streaming path must track summaries)
            with ZipFile(output_path, "r") as zf:
                summaries_raw = json.loads(zf.read("summaries.json"))
                assert len(summaries_raw) == 1

            # Verify the file can be read back and events expand correctly
            read_log = read_eval_log(output_path)
            assert read_log.samples is not None
            read_sample = read_log.samples[0]
            read_model_events = [
                e for e in read_sample.events if isinstance(e, ModelEvent)
            ]
            # After read, events_data is resolved (inputs restored)
            for me in read_model_events:
                assert len(me.input) > 0
                assert me.input_refs is None


async def test_streaming_recovery_sample_with_no_events() -> None:
    """Samples with segments but no events still appear in the ZIP and summaries.

    Streaming recovery must not silently drop samples whose segments yielded
    no events - the sample is real (it has a summary) and skipping it would
    desync the ZIP entries from summaries.json.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            buffer_dir = os.path.join(temp_dir, ".buffer", "test")
            os.makedirs(buffer_dir, exist_ok=True)

            # One segment with zero events
            _write_segment_zip(buffer_dir, 1, "sample1", 1, events=[])
            segments = [Segment(id=1, last_event_id=0, last_attachment_id=0)]
            summary = _make_summary(id="sample1", epoch=1, completed=True)
            manifest = Manifest(
                samples=[SampleManifest(summary=summary, segments=[1])],
                segments=segments,
            )
            with open(os.path.join(buffer_dir, "manifest.json"), "w") as f:
                f.write(manifest.model_dump_json())
            with open(os.path.join(buffer_dir, ".keep"), "w") as f:
                pass

            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            with ZipFile(output_path, "r") as zf:
                sample_names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("samples/") and n.endswith(".json")
                ]
                assert len(sample_names) == 1
                raw = json.loads(zf.read(sample_names[0]))
                summaries_raw = json.loads(zf.read("summaries.json"))

            # Sample entry and summary entry are both present and consistent
            assert raw["id"] == "sample1"
            assert raw["events"] == []
            assert raw["messages"] == []
            assert len(summaries_raw) == 1
            assert summaries_raw[0]["id"] == "sample1"

            # Schema-complete keyset: every EvalSample field must be emitted
            expected_keys = set(EvalSample.model_fields.keys())
            assert expected_keys.issubset(raw.keys())
            assert set(raw.keys()) <= expected_keys


async def test_streaming_recovery_handles_many_attachments() -> None:
    """Streaming recovery accumulates attachments on disk, not in RAM.

    Creates a sample with 50 segments, each producing a unique attachment
    of ~100 KB (content large enough that condense_event promotes it to
    an attachment). Verifies all attachments make it into the recovered
    ZIP and round-trip through read_eval_log.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            buffer_dir = os.path.join(temp_dir, ".buffer", "test")
            os.makedirs(buffer_dir, exist_ok=True)

            segments = []
            num_segments = 50
            attachment_chunk = "x" * 100_000  # 100KB, above condense threshold
            for i in range(1, num_segments + 1):
                unique_content = f"{attachment_chunk}-seg-{i}"
                event = ModelEvent(
                    model="mockllm/model",
                    input=[ChatMessageUser(content=unique_content)],
                    tools=[],
                    tool_choice="auto",
                    config=GenerateConfig(),
                    output=ModelOutput.from_content(
                        model="mockllm/model", content=f"reply {i}"
                    ),
                )
                event_dict = to_jsonable_python(event, exclude_none=True)
                _write_segment_zip(buffer_dir, i, "sample1", 1, [event_dict])
                segments.append(Segment(id=i, last_event_id=i, last_attachment_id=0))

            summary = _make_summary(id="sample1", epoch=1, completed=True)
            manifest = Manifest(
                samples=[
                    SampleManifest(summary=summary, segments=[s.id for s in segments])
                ],
                segments=segments,
            )
            with open(os.path.join(buffer_dir, "manifest.json"), "w") as f:
                f.write(manifest.model_dump_json())
            with open(os.path.join(buffer_dir, ".keep"), "w") as f:
                pass

            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            with ZipFile(output_path, "r") as zf:
                sample_names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("samples/") and n.endswith(".json")
                ]
                assert len(sample_names) == 1
                raw = json.loads(zf.read(sample_names[0]))

            assert len(raw["attachments"]) == num_segments
            values = set(raw["attachments"].values())
            for i in range(1, num_segments + 1):
                assert f"{attachment_chunk}-seg-{i}" in values

            read_log = read_eval_log(output_path, resolve_attachments="full")
            assert read_log.samples is not None
            read_sample = read_log.samples[0]
            first_model_event = next(
                e for e in read_sample.events if isinstance(e, ModelEvent)
            )
            assert len(first_model_event.input[0].text) >= 100_000


async def test_streaming_recovery_sample_id_with_unsafe_chars() -> None:
    """Sample ids with path-unsafe characters must not break recovery."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            buffer_dir = os.path.join(temp_dir, ".buffer", "test")
            os.makedirs(buffer_dir, exist_ok=True)

            unsafe_id = "../etc/passwd"  # contains / and ..
            event = ModelEvent(
                model="mockllm/model",
                input=[ChatMessageUser(content="hi")],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput.from_content(model="mockllm/model", content="hello"),
            )
            event_dict = to_jsonable_python(event, exclude_none=True)
            _write_segment_zip(buffer_dir, 1, unsafe_id, 1, [event_dict])

            segment = Segment(id=1, last_event_id=1, last_attachment_id=0)
            summary = _make_summary(id=unsafe_id, epoch=1, completed=True)
            manifest = Manifest(
                samples=[SampleManifest(summary=summary, segments=[1])],
                segments=[segment],
            )
            with open(os.path.join(buffer_dir, "manifest.json"), "w") as f:
                f.write(manifest.model_dump_json())
            with open(os.path.join(buffer_dir, ".keep"), "w") as f:
                pass

            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            # Recovery must succeed despite the unsafe id
            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            # The recovery having completed is itself the key assertion.
            # Verify the recovered log is readable and contains the unsafe id
            read_log = read_eval_log(output_path)
            assert read_log.samples is not None
            assert len(read_log.samples) == 1
            assert read_log.samples[0].id == unsafe_id  # id preserved in manifest

            # Guard against path traversal: nothing should be written outside
            # the .eval zip (e.g. no etc/passwd on disk next to it).
            assert not os.path.exists(os.path.join(temp_dir, "etc"))
            assert not os.path.exists(os.path.join(temp_dir, "etc", "passwd"))


async def test_streaming_recovery_merges_segment_attachment_pool() -> None:
    """Segment attachment pool must be merged into recovered ZIP.

    The live buffer writer condenses events into `attachment://<hash>` refs
    and stores content in `SampleData.attachments`. Recovery must merge
    the pool back in -- if it doesn't, refs dangle and `read_eval_log`
    can't resolve them.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            buffer_dir = os.path.join(temp_dir, ".buffer", "test")
            os.makedirs(buffer_dir, exist_ok=True)

            # Large content (would be condensed at write time by the live writer)
            payload = "x" * 5_000
            hash_ = "deadbeefcafe0000deadbeefcafe0000"

            # Build a model event with a pre-condensed `attachment://<hash>` ref
            # (mimicking what the live buffer writer stores after _condense_event)
            event = ModelEvent(
                model="mockllm/model",
                input=[ChatMessageUser(content=f"{ATTACHMENT_PROTOCOL}{hash_}")],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput.from_content(model="mockllm/model", content="hello"),
            )
            event_dict = to_jsonable_python(event, exclude_none=True)

            # Write segment with BOTH the pre-condensed event AND the attachment pool
            _write_segment_zip(
                buffer_dir,
                1,
                "sample1",
                1,
                [event_dict],
                attachments=[
                    AttachmentData(
                        id=1,
                        sample_id="sample1",
                        epoch=1,
                        hash=hash_,
                        content=payload,
                    )
                ],
            )

            segment = Segment(id=1, last_event_id=1, last_attachment_id=1)
            summary = _make_summary(id="sample1", epoch=1, completed=True)
            manifest = Manifest(
                samples=[SampleManifest(summary=summary, segments=[1])],
                segments=[segment],
            )
            with open(os.path.join(buffer_dir, "manifest.json"), "w") as f:
                f.write(manifest.model_dump_json())
            with open(os.path.join(buffer_dir, ".keep"), "w") as f:
                pass

            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            # The recovered ZIP must contain the attachment content keyed by hash
            with ZipFile(output_path, "r") as zf:
                sample_names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("samples/") and n.endswith(".json")
                ]
                assert len(sample_names) == 1
                raw = json.loads(zf.read(sample_names[0]))

            assert raw["attachments"].get(hash_) == payload, (
                f"Expected attachment {hash_} to be merged from segment pool, "
                f"got keys={list(raw['attachments'].keys())}"
            )

            # End-to-end resolution must work
            read_log = read_eval_log(output_path, resolve_attachments="full")
            assert read_log.samples is not None
            read_sample = read_log.samples[0]
            first_model_event = next(
                e for e in read_sample.events if isinstance(e, ModelEvent)
            )
            # After resolve, the ref should have expanded to payload
            assert payload in first_model_event.input[0].text


def _write_sample_init_event_dict(
    sample: Sample,
) -> dict[str, JsonValue]:
    """Return a JSON-serializable dict for a SampleInitEvent."""
    event = SampleInitEvent(sample=sample, state=None)
    return to_jsonable_python(event, exclude_none=False)


def _write_sample_limit_event_dict(
    type: str, limit: float | None, message: str = "hit"
) -> dict[str, JsonValue]:
    """Return a JSON-serializable dict for a SampleLimitEvent."""
    event = SampleLimitEvent(type=type, limit=limit, message=message)  # type: ignore[arg-type]
    return to_jsonable_python(event, exclude_none=False)


async def test_streaming_recovery_emits_all_eval_sample_fields() -> None:
    """Streaming recovery emits every EvalSample field (keyset complete).

    A fixture with no SampleInitEvent/SampleLimitEvent; verify defaults
    match what a pydantic-serialized EvalSample would produce.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path, _ = _create_filestore_fixture(
                temp_dir, num_segments=2, completed=True
            )
            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            with ZipFile(output_path, "r") as zf:
                sample_names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("samples/") and n.endswith(".json")
                ]
                assert len(sample_names) == 1
                raw = json.loads(zf.read(sample_names[0]))

            expected_keys = set(EvalSample.model_fields.keys())
            missing = expected_keys - set(raw.keys())
            unexpected = set(raw.keys()) - expected_keys
            assert not missing, f"Missing keys: {missing}"
            assert not unexpected, f"Unexpected keys: {unexpected}"

            # Defaults for a fixture with no init/limit events
            assert raw["sandbox"] is None
            assert raw["files"] is None
            assert raw["setup"] is None
            assert raw["store"] == {}
            assert raw["timelines"] is None
            assert raw["invalidation"] is None
            assert raw["error_retries"] is None
            assert raw["limit"] is None

            # Read-back round-trip: keyset equals emitted keyset
            read_log = read_eval_log(output_path)
            assert read_log.samples is not None
            read_keys = set(read_log.samples[0].model_dump(mode="json").keys())
            assert read_keys == set(raw.keys())


@pytest.mark.parametrize("fixture_completed", [False, True])
async def test_streaming_recovery_marks_summary_completed(
    fixture_completed: bool,
) -> None:
    """Recovered summaries always carry ``completed=True``.

    Matches the invariant of ``EvalSample.summary()`` at ``_log.py:487``
    -- once a sample has been written, its summary is "completed" in the
    log-index sense, regardless of whether the original run finished.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path, _ = _create_filestore_fixture(
                temp_dir, num_segments=2, completed=fixture_completed
            )
            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            with ZipFile(output_path, "r") as zf:
                summaries = json.loads(zf.read("summaries.json"))

            assert len(summaries) == 1
            assert summaries[0]["completed"] is True


async def test_streaming_recovery_carries_sample_init_fields() -> None:
    """Per-sample files/setup propagate from SampleInitEvent.

    Note: sandbox propagation from SampleInitEvent through JSON round-trip
    is broken by a pre-existing ``Sample.__init__`` issue (dict form of
    sandbox resolves to None). Recovery still populates ``sandbox`` from
    the eval-level spec -- see ``test_streaming_recovery_inherits_eval_sandbox``.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            buffer_dir = os.path.join(temp_dir, ".buffer", "test")
            os.makedirs(buffer_dir, exist_ok=True)

            init_event = _write_sample_init_event_dict(
                Sample(
                    input="hello",
                    target="hi",
                    files={"a.txt": "contents"},
                    setup="echo hi",
                )
            )
            model_event = _make_model_event_dict("response")

            _write_segment_zip(buffer_dir, 1, "sample1", 1, [init_event, model_event])
            segments = [Segment(id=1, last_event_id=2, last_attachment_id=0)]
            summary = _make_summary(id="sample1", epoch=1, completed=True)
            manifest = Manifest(
                samples=[SampleManifest(summary=summary, segments=[1])],
                segments=segments,
            )
            with open(os.path.join(buffer_dir, "manifest.json"), "w") as f:
                f.write(manifest.model_dump_json())
            with open(os.path.join(buffer_dir, ".keep"), "w") as f:
                pass

            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            with ZipFile(output_path, "r") as zf:
                sample_names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("samples/") and n.endswith(".json")
                ]
                raw = json.loads(zf.read(sample_names[0]))

            assert raw["files"] == ["a.txt"]
            assert raw["setup"] == "echo hi"


async def test_streaming_recovery_inherits_eval_sandbox() -> None:
    """When no SampleInitEvent, sandbox falls back to eval-level spec."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path, _ = _create_filestore_fixture(
                temp_dir, num_segments=1, completed=True
            )
            _write_crashed_eval(
                eval_path, sandbox=SandboxEnvironmentSpec(type="docker")
            )
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            with ZipFile(output_path, "r") as zf:
                sample_names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("samples/") and n.endswith(".json")
                ]
                raw = json.loads(zf.read(sample_names[0]))

            assert raw["sandbox"] is not None
            assert raw["sandbox"]["type"] == "docker"
            # No per-sample init → files/setup stay None
            assert raw["files"] is None
            assert raw["setup"] is None


async def test_streaming_recovery_captures_sample_limit() -> None:
    """SampleLimitEvent propagates into EvalSampleLimit on the sample."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            buffer_dir = os.path.join(temp_dir, ".buffer", "test")
            os.makedirs(buffer_dir, exist_ok=True)

            model_event = _make_model_event_dict("response")
            limit_event = _write_sample_limit_event_dict(
                type="token", limit=1000.0, message="hit"
            )

            _write_segment_zip(buffer_dir, 1, "sample1", 1, [model_event, limit_event])
            segments = [Segment(id=1, last_event_id=2, last_attachment_id=0)]
            summary = _make_summary(id="sample1", epoch=1, completed=True)
            manifest = Manifest(
                samples=[SampleManifest(summary=summary, segments=[1])],
                segments=segments,
            )
            with open(os.path.join(buffer_dir, "manifest.json"), "w") as f:
                f.write(manifest.model_dump_json())
            with open(os.path.join(buffer_dir, ".keep"), "w") as f:
                pass

            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            with ZipFile(output_path, "r") as zf:
                sample_names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("samples/") and n.endswith(".json")
                ]
                raw = json.loads(zf.read(sample_names[0]))

            assert raw["limit"] == {"type": "token", "limit": 1000.0}


async def test_streaming_recovery_empty_pools_emits_null_events_data() -> None:
    """events_data must be the literal null (key present) when pools are empty."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            buffer_dir = os.path.join(temp_dir, ".buffer", "test")
            os.makedirs(buffer_dir, exist_ok=True)

            # A single segment with no events → empty pools
            _write_segment_zip(buffer_dir, 1, "sample1", 1, events=[])
            segments = [Segment(id=1, last_event_id=0, last_attachment_id=0)]
            summary = _make_summary(id="sample1", epoch=1, completed=True)
            manifest = Manifest(
                samples=[SampleManifest(summary=summary, segments=[1])],
                segments=segments,
            )
            with open(os.path.join(buffer_dir, "manifest.json"), "w") as f:
                f.write(manifest.model_dump_json())
            with open(os.path.join(buffer_dir, ".keep"), "w") as f:
                pass

            _write_crashed_eval(eval_path)
            db_dir = os.path.join(temp_dir, "empty_db_dir")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            with ZipFile(output_path, "r") as zf:
                sample_names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("samples/") and n.endswith(".json")
                ]
                raw = json.loads(zf.read(sample_names[0]))

            assert "events_data" in raw
            assert raw["events_data"] is None
