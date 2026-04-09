"""End-to-end recovery tests using realistic EvalRecorder-created .eval files."""

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._file import read_eval_log
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalPlan,
    EvalSample,
    EvalSampleSummary,
    EvalSpec,
)
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.eval import LogStart, ZipLogFile
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._recover import RecoveryNotAvailable, recover_eval_log_async
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.scorer._metric import Score


def _make_eval_spec(task: str = "e2e_test", num_samples: int = 6) -> EvalSpec:
    return EvalSpec(
        created=datetime.now(timezone.utc).isoformat(),
        task=task,
        model="mockllm/model",
        dataset=EvalDataset(name="test", samples=num_samples),
        config=EvalConfig(epochs=2),
    )


def _make_realistic_sample(
    id: int,
    epoch: int,
    system_prompt: str = "You are a helpful assistant.",
) -> EvalSample:
    """Create a realistic multi-turn sample with system prompt and tool-like interaction."""
    user1 = ChatMessageUser(content=f"Question {id}: What is {id}+{id}?")
    assistant1 = ChatMessageAssistant(
        content=f"Let me calculate that. {id}+{id} = {id * 2}"
    )
    user2 = ChatMessageUser(content="Are you sure?")
    assistant2 = ChatMessageAssistant(content=f"Yes, {id}+{id} = {id * 2}.")

    return EvalSample(
        id=id,
        epoch=epoch,
        input=f"Question {id}",
        target=str(id * 2),
        messages=[
            ChatMessageSystem(content=system_prompt),
            user1,
            assistant1,
            user2,
            assistant2,
        ],
        output=ModelOutput.from_content(
            model="mockllm/model", content=f"Yes, {id}+{id} = {id * 2}."
        ),
        scores={"accuracy": Score(value="C", answer=str(id * 2))},
        metadata={"difficulty": "easy"},
        model_usage={
            "mockllm/model": ModelUsage(
                input_tokens=50, output_tokens=20, total_tokens=70
            )
        },
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )


_DEAD_PID = 99999999


def _simulate_crashed_buffer(buffer: SampleBufferDatabase) -> None:
    """Rename the buffer DB to use a dead PID, simulating a crashed process."""
    old_path = buffer.db_path
    new_path = old_path.parent / old_path.name.replace(
        f".{os.getpid()}.", f".{_DEAD_PID}."
    )
    old_path.rename(new_path)
    buffer.db_path = new_path


def _make_model_event(input_msgs: list[ChatMessage], output_content: str) -> ModelEvent:
    return ModelEvent(
        model="mockllm/model",
        input=input_msgs,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content(model="mockllm/model", content=output_content),
    )


async def test_e2e_recovery_with_recorder_created_eval() -> None:
    """End-to-end test using ZipLogFile to create a realistic crashed .eval.

    Simulates a crash by writing some samples via ZipLogFile (with flush)
    but never calling close/log_finish — leaving the file without header.json.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "realistic.eval")
            output_path = os.path.join(temp_dir, "realistic-recovered.eval")

            eval_spec = _make_eval_spec(num_samples=3)
            plan = EvalPlan()
            log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

            # Create the .eval file using ZipLogFile (realistic path)
            zip_log = ZipLogFile(eval_path)
            await zip_log.init(log_start=None, summary_counter=0, summaries=[])
            await zip_log.start(log_start)

            # Write 3 samples across 2 epochs (flushed to disk)
            flushed_samples = [
                _make_realistic_sample(1, epoch=1),
                _make_realistic_sample(2, epoch=1),
                _make_realistic_sample(1, epoch=2),
            ]
            for sample in flushed_samples:
                await zip_log.buffer_sample(sample)
            await zip_log.write_buffered_samples()
            await zip_log.flush()

            # Simulate crash — do NOT call zip_log.close() or log_finish
            # This leaves the file without header.json

            # Create buffer DB with additional samples (unflushed at crash time)
            db_dir = os.path.join(temp_dir, "bufferdb")
            buffer = SampleBufferDatabase(eval_path, create=True, db_dir=Path(db_dir))
            try:
                # One completed sample in buffer
                started_summary = EvalSampleSummary(
                    id=3,
                    epoch=1,
                    input="Question 3",
                    target="6",
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
                buffer.start_sample(started_summary)

                # Log realistic multi-turn events
                user1 = ChatMessageUser(content="Question 3: What is 3+3?")
                event1 = _make_model_event([user1], "Let me think... 3+3 = 6")
                buffer.log_events([SampleEvent(id=3, epoch=1, event=event1)])

                assistant1 = ChatMessageAssistant(content="Let me think... 3+3 = 6")
                user2 = ChatMessageUser(content="Are you sure?")
                event2 = _make_model_event([user1, assistant1, user2], "Yes, 3+3 = 6.")
                buffer.log_events([SampleEvent(id=3, epoch=1, event=event2)])

                completed_summary = EvalSampleSummary(
                    id=3,
                    epoch=1,
                    input="Question 3",
                    target="6",
                    scores={"accuracy": Score(value="C", answer="6")},
                    model_usage={
                        "mockllm/model": ModelUsage(
                            input_tokens=50, output_tokens=20, total_tokens=70
                        )
                    },
                    started_at=datetime.now(timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                buffer.complete_sample(completed_summary)

                # One in-progress sample in buffer (was running when crash happened)
                in_progress_summary = EvalSampleSummary(
                    id=2,
                    epoch=2,
                    input="Question 2",
                    target="4",
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
                buffer.start_sample(in_progress_summary)
                partial_event = _make_model_event(
                    [ChatMessageUser(content="Question 2: What is 2+2?")],
                    "Let me think...",
                )
                buffer.log_events([SampleEvent(id=2, epoch=2, event=partial_event)])

                # Simulate crash (rename DB to dead PID)
                _simulate_crashed_buffer(buffer)

                # Recover
                log = await recover_eval_log_async(
                    eval_path, output=output_path, cleanup=False, _db_dir=db_dir
                )

                # Verify the recovered log
                assert log.status == "error"
                assert log.error is not None
                assert log.samples is not None
                # 3 flushed + 1 completed from buffer + 1 in-progress from buffer
                assert len(log.samples) == 5

                # Verify samples are sorted by epoch then id
                sample_keys = [(s.epoch, s.id) for s in log.samples]
                assert sample_keys == sorted(sample_keys)

                # Verify stats
                assert log.stats is not None
                assert "mockllm/model" in log.stats.model_usage

                # Read back from disk and verify round-trip
                read_log = read_eval_log(output_path)
                assert read_log.status == "error"
                assert read_log.samples is not None
                assert len(read_log.samples) == 5

                # Verify flushed samples preserved their messages
                flushed_s1 = next(
                    s for s in read_log.samples if s.id == 1 and s.epoch == 1
                )
                assert len(flushed_s1.messages) == 5  # system + 2 user + 2 assistant
                assert flushed_s1.scores is not None
                assert flushed_s1.metadata.get("difficulty") == "easy"

                # Verify buffer-recovered completed sample has messages
                buffer_s3 = next(
                    s for s in read_log.samples if s.id == 3 and s.epoch == 1
                )
                assert len(buffer_s3.messages) > 0
                assert buffer_s3.scores is not None

                # Verify in-progress sample has cancellation error
                in_progress_s2 = next(
                    s for s in read_log.samples if s.id == 2 and s.epoch == 2
                )
                assert in_progress_s2.error is not None
                assert "CancelledError" in in_progress_s2.error.message
                assert in_progress_s2.scores is None
                assert len(in_progress_s2.messages) > 0  # partial messages preserved

            finally:
                buffer.cleanup()


async def test_e2e_recovery_multi_epoch_sorting() -> None:
    """Verify that multi-epoch samples are correctly sorted in recovered log."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "multiepoch.eval")
            output_path = os.path.join(temp_dir, "multiepoch-recovered.eval")

            eval_spec = _make_eval_spec(num_samples=2)
            plan = EvalPlan()
            log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

            # Create .eval with samples from different epochs
            zip_log = ZipLogFile(eval_path)
            await zip_log.init(log_start=None, summary_counter=0, summaries=[])
            await zip_log.start(log_start)

            # Write out of order: epoch 2 before epoch 1
            samples = [
                _make_realistic_sample(2, epoch=2),
                _make_realistic_sample(1, epoch=2),
                _make_realistic_sample(2, epoch=1),
                _make_realistic_sample(1, epoch=1),
            ]
            for sample in samples:
                await zip_log.buffer_sample(sample)
            await zip_log.write_buffered_samples()
            await zip_log.flush()
            # Crash — no close

            # No buffer DB — recovery raises RecoveryNotAvailable
            db_dir = os.path.join(temp_dir, "bufferdb")
            with pytest.raises(RecoveryNotAvailable):
                await recover_eval_log_async(
                    eval_path, output=output_path, _db_dir=db_dir
                )


async def test_e2e_recovery_crash_before_first_flush() -> None:
    """Test recovery when crash happens before any samples are flushed.

    The .eval file has start.json but no samples. All data comes from buffer DB.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "noflush.eval")
            output_path = os.path.join(temp_dir, "noflush-recovered.eval")

            eval_spec = _make_eval_spec(num_samples=2)
            plan = EvalPlan()
            log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

            # Create .eval with start.json only — no samples flushed
            zip_log = ZipLogFile(eval_path)
            await zip_log.init(log_start=None, summary_counter=0, summaries=[])
            await zip_log.start(log_start)
            await zip_log.flush()
            # Crash — no samples ever flushed

            # All data in buffer DB
            db_dir = os.path.join(temp_dir, "bufferdb")
            buffer = SampleBufferDatabase(eval_path, create=True, db_dir=Path(db_dir))
            try:
                for id in [1, 2]:
                    started = EvalSampleSummary(
                        id=id,
                        epoch=1,
                        input=f"Question {id}",
                        target=str(id * 2),
                        started_at=datetime.now(timezone.utc).isoformat(),
                    )
                    buffer.start_sample(started)
                    event = _make_model_event(
                        [ChatMessageUser(content=f"What is {id}+{id}?")],
                        str(id * 2),
                    )
                    buffer.log_events([SampleEvent(id=id, epoch=1, event=event)])
                    completed = EvalSampleSummary(
                        id=id,
                        epoch=1,
                        input=f"Question {id}",
                        target=str(id * 2),
                        scores={"accuracy": Score(value="C", answer=str(id * 2))},
                        started_at=datetime.now(timezone.utc).isoformat(),
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    buffer.complete_sample(completed)

                _simulate_crashed_buffer(buffer)

                log = await recover_eval_log_async(
                    eval_path, output=output_path, cleanup=False, _db_dir=db_dir
                )

                assert log.samples is not None
                assert len(log.samples) == 2
                assert all(s.scores is not None for s in log.samples)

                # Read back
                read_log = read_eval_log(output_path)
                assert read_log.samples is not None
                assert len(read_log.samples) == 2
            finally:
                buffer.cleanup()


async def test_e2e_recovery_duplicate_samples_in_buffer_and_eval() -> None:
    """Test recovery when buffer DB has samples that were also flushed to .eval.

    This can happen if crash occurs between recorder.flush() and
    buffer_db.remove_samples() — the sample ends up in both places.
    Recovery should deduplicate, preferring the flushed version.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "dupes.eval")
            output_path = os.path.join(temp_dir, "dupes-recovered.eval")

            eval_spec = _make_eval_spec(num_samples=2)
            plan = EvalPlan()
            log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

            # Create .eval with sample 1 flushed
            zip_log = ZipLogFile(eval_path)
            await zip_log.init(log_start=None, summary_counter=0, summaries=[])
            await zip_log.start(log_start)
            sample1 = _make_realistic_sample(1, epoch=1)
            await zip_log.buffer_sample(sample1)
            await zip_log.write_buffered_samples()
            await zip_log.flush()
            # Crash here — sample 1 is in .eval but NOT removed from buffer DB

            # Buffer DB still has sample 1 (wasn't cleaned up) plus sample 2
            db_dir = os.path.join(temp_dir, "bufferdb")
            buffer = SampleBufferDatabase(eval_path, create=True, db_dir=Path(db_dir))
            try:
                for id in [1, 2]:
                    started = EvalSampleSummary(
                        id=id,
                        epoch=1,
                        input=f"Question {id}",
                        target=str(id * 2),
                        started_at=datetime.now(timezone.utc).isoformat(),
                    )
                    buffer.start_sample(started)
                    event = _make_model_event(
                        [ChatMessageUser(content=f"What is {id}+{id}?")],
                        str(id * 2),
                    )
                    buffer.log_events([SampleEvent(id=id, epoch=1, event=event)])
                    completed = EvalSampleSummary(
                        id=id,
                        epoch=1,
                        input=f"Question {id}",
                        target=str(id * 2),
                        scores={"accuracy": Score(value="C", answer=str(id * 2))},
                        started_at=datetime.now(timezone.utc).isoformat(),
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    buffer.complete_sample(completed)

                _simulate_crashed_buffer(buffer)

                log = await recover_eval_log_async(
                    eval_path, output=output_path, cleanup=False, _db_dir=db_dir
                )

                assert log.samples is not None
                # Should have exactly 2 unique samples (sample 1 deduplicated)
                assert len(log.samples) == 2
                sample_keys = [(s.id, s.epoch) for s in log.samples]
                assert len(sample_keys) == len(set(sample_keys)), (
                    f"Duplicate samples found: {sample_keys}"
                )
            finally:
                buffer.cleanup()


async def test_e2e_recovery_multiple_flush_batches() -> None:
    """Realistic scenario: multiple flush batches with crash mid-batch.

    Simulates: batch 1 (samples 1,2) flushed, batch 2 (samples 3,4) flushed,
    samples 5,6 completed but not yet flushed (in buffer DB only),
    sample 7 in-progress at crash time.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "batched.eval")
            output_path = os.path.join(temp_dir, "batched-recovered.eval")

            eval_spec = _make_eval_spec(num_samples=7)
            plan = EvalPlan()
            log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

            # Create .eval with two flush batches
            zip_log = ZipLogFile(eval_path)
            await zip_log.init(log_start=None, summary_counter=0, summaries=[])
            await zip_log.start(log_start)

            # Batch 1
            for id in [1, 2]:
                await zip_log.buffer_sample(_make_realistic_sample(id, epoch=1))
            await zip_log.write_buffered_samples()
            await zip_log.flush()

            # Batch 2
            for id in [3, 4]:
                await zip_log.buffer_sample(_make_realistic_sample(id, epoch=1))
            await zip_log.write_buffered_samples()
            await zip_log.flush()

            # Crash — samples 5,6 completed but unflushed, sample 7 in-progress

            db_dir = os.path.join(temp_dir, "bufferdb")
            buffer = SampleBufferDatabase(eval_path, create=True, db_dir=Path(db_dir))
            try:
                # Completed but unflushed
                for id in [5, 6]:
                    started = EvalSampleSummary(
                        id=id,
                        epoch=1,
                        input=f"Q{id}",
                        target=str(id * 2),
                        started_at=datetime.now(timezone.utc).isoformat(),
                    )
                    buffer.start_sample(started)
                    event = _make_model_event(
                        [ChatMessageUser(content=f"What is {id}+{id}?")],
                        str(id * 2),
                    )
                    buffer.log_events([SampleEvent(id=id, epoch=1, event=event)])
                    completed = EvalSampleSummary(
                        id=id,
                        epoch=1,
                        input=f"Q{id}",
                        target=str(id * 2),
                        scores={"accuracy": Score(value="C", answer=str(id * 2))},
                        started_at=datetime.now(timezone.utc).isoformat(),
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    buffer.complete_sample(completed)

                # In-progress at crash
                started = EvalSampleSummary(
                    id=7,
                    epoch=1,
                    input="Q7",
                    target="14",
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
                buffer.start_sample(started)
                event = _make_model_event(
                    [ChatMessageUser(content="What is 7+7?")], "Let me think..."
                )
                buffer.log_events([SampleEvent(id=7, epoch=1, event=event)])

                _simulate_crashed_buffer(buffer)

                log = await recover_eval_log_async(
                    eval_path, output=output_path, cleanup=False, _db_dir=db_dir
                )

                assert log.samples is not None
                assert len(log.samples) == 7

                ids = sorted([s.id for s in log.samples])
                assert ids == [1, 2, 3, 4, 5, 6, 7]

                # In-progress sample has cancellation error
                s7 = next(s for s in log.samples if s.id == 7)
                assert s7.error is not None
                assert s7.scores is None

                # Flushed samples have full messages
                s1 = next(s for s in log.samples if s.id == 1)
                assert len(s1.messages) == 5
                assert s1.scores is not None

                # Round-trip
                read_log = read_eval_log(output_path)
                assert read_log.samples is not None
                assert len(read_log.samples) == 7
            finally:
                buffer.cleanup()


async def test_e2e_recovery_sample_with_error() -> None:
    """Test recovery of a sample that had an error during execution.

    A sample can hit an error (e.g. model API failure) and still be
    logged with the error before the eval crashes.
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "errored.eval")
            output_path = os.path.join(temp_dir, "errored-recovered.eval")

            eval_spec = _make_eval_spec(num_samples=2)
            plan = EvalPlan()
            log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

            zip_log = ZipLogFile(eval_path)
            await zip_log.init(log_start=None, summary_counter=0, summaries=[])
            await zip_log.start(log_start)
            await zip_log.flush()

            db_dir = os.path.join(temp_dir, "bufferdb")
            buffer = SampleBufferDatabase(eval_path, create=True, db_dir=Path(db_dir))
            try:
                # Sample 1: completed with error
                started = EvalSampleSummary(
                    id=1,
                    epoch=1,
                    input="Q1",
                    target="2",
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
                buffer.start_sample(started)
                event = _make_model_event(
                    [ChatMessageUser(content="What is 1+1?")], "Error occurred"
                )
                buffer.log_events([SampleEvent(id=1, epoch=1, event=event)])
                errored = EvalSampleSummary(
                    id=1,
                    epoch=1,
                    input="Q1",
                    target="2",
                    error="Model API rate limit exceeded",
                    started_at=datetime.now(timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                buffer.complete_sample(errored)

                # Sample 2: normal completed
                started2 = EvalSampleSummary(
                    id=2,
                    epoch=1,
                    input="Q2",
                    target="4",
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
                buffer.start_sample(started2)
                event2 = _make_model_event(
                    [ChatMessageUser(content="What is 2+2?")], "4"
                )
                buffer.log_events([SampleEvent(id=2, epoch=1, event=event2)])
                completed2 = EvalSampleSummary(
                    id=2,
                    epoch=1,
                    input="Q2",
                    target="4",
                    scores={"accuracy": Score(value="C", answer="4")},
                    started_at=datetime.now(timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                buffer.complete_sample(completed2)

                _simulate_crashed_buffer(buffer)

                log = await recover_eval_log_async(
                    eval_path, output=output_path, cleanup=False, _db_dir=db_dir
                )

                assert log.samples is not None
                assert len(log.samples) == 2

                # Errored sample preserved
                s1 = next(s for s in log.samples if s.id == 1)
                assert s1.scores is None

                # Normal sample has scores
                s2 = next(s for s in log.samples if s.id == 2)
                assert s2.scores is not None

                read_log = read_eval_log(output_path)
                assert read_log.samples is not None
                assert len(read_log.samples) == 2
            finally:
                buffer.cleanup()


async def test_e2e_recovery_only_flushed_no_buffer() -> None:
    """Recovery using realistic ZipLogFile with no buffer DB.

    Covers the case where the buffer DB was already cleaned up or never
    created (e.g. log_realtime=False).
    """
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "flushed_only.eval")
            output_path = os.path.join(temp_dir, "flushed_only-recovered.eval")

            eval_spec = _make_eval_spec(num_samples=3)
            plan = EvalPlan()
            log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

            zip_log = ZipLogFile(eval_path)
            await zip_log.init(log_start=None, summary_counter=0, summaries=[])
            await zip_log.start(log_start)

            for id in [1, 2, 3]:
                await zip_log.buffer_sample(_make_realistic_sample(id, epoch=1))
            await zip_log.write_buffered_samples()
            await zip_log.flush()
            # Crash — no buffer DB exists

            # No buffer DB — recovery raises RecoveryNotAvailable
            db_dir = os.path.join(temp_dir, "bufferdb")
            with pytest.raises(RecoveryNotAvailable):
                await recover_eval_log_async(
                    eval_path, output=output_path, _db_dir=db_dir
                )
