import io
import math
import os
import tempfile
from datetime import datetime, timezone
from typing import Literal

import pytest
from pydantic_core import PydanticSerializationError
from test_helpers.utils import skip_if_trio
from typing_extensions import override

from inspect_ai import Task, eval
from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.content import ContentDocument
from inspect_ai._util.file import FileInfo, filesystem
from inspect_ai.dataset import Sample
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sandbox import SandboxEvent
from inspect_ai.event._score_edit import ScoreEditEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.event._subtask import SubtaskEvent
from inspect_ai.event._timeline import TimelineEvent, timeline_build
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log import read_eval_log
from inspect_ai.log._edit import ProvenanceData
from inspect_ai.log._file import (
    ReadEvalLogsProgress,
    list_eval_logs,
    log_files_from_ls,
    read_eval_log_headers,
    read_eval_log_sample,
    write_eval_log,
)
from inspect_ai.log._log import EvalLog, EvalSample
from inspect_ai.model import get_model
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import exact
from inspect_ai.solver import (
    Generate,
    TaskState,
    generate,
    solver,
)


def log_path(file: str) -> str:
    return os.path.join("tests", "log", "test_eval_log", f"{file}.txt")


def read_log(file: str, header_only: bool = False) -> EvalLog:
    return read_eval_log(file, header_only=header_only, format="json")


class NotSerializable:
    name: str


def test_ignore_unserializable():
    @solver
    def inject_unserializable():
        async def solve(state: TaskState, generate: Generate):
            state.metadata["not serializable"] = NotSerializable
            return state

        return solve

    task = Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        solver=[inject_unserializable(), generate()],
    )

    try:
        eval(tasks=task, model="mockllm/model")
    except PydanticSerializationError:
        assert False, "Eval raised Pydantic serialization error."


def test_read_nan():
    def check_for_nan(log):
        assert math.isnan(log.results.metrics.get("accuracy").value)

    log_file = log_path("log_with_nan")
    check_for_nan(read_log(log_file))
    check_for_nan(read_log(log_file, header_only=True))


def test_fail_invalid():
    check_log_raises(log_path("log_invalid"))


def test_fail_version():
    check_log_raises(log_path("log_version_3"))


def test_valid_log_header():
    log = read_log(log_path("log_valid"), header_only=True)
    assert log.eval.metadata["meaning_of_life"] == 42


def test_migrate_length_stop_reason():
    log = read_log(log_path("log_length_stop_reason"))
    assert log.samples[0].output.stop_reason == "max_tokens"


def test_read_sample():
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    with tempfile.TemporaryDirectory() as tmpdirname:
        # try out json file
        sample = read_eval_log_sample(log_file, 1, 1)
        assert sample.target == " Yes"

        # try out eval file
        log = read_eval_log(log_file)
        eval_log_path = os.path.join(tmpdirname, "new_log.eval")
        write_eval_log(log, eval_log_path)
        sample = read_eval_log_sample(eval_log_path, 1, 1)
        assert sample.target == " Yes"


def test_read_sample_by_uuid():
    log_files = [
        os.path.join("tests", "log", "test_eval_log", file)
        for file in ["log_read_sample.json", "log_read_sample.eval"]
    ]
    for log_file in log_files:
        sampleA = read_eval_log_sample(log_file, id=1, epoch=1)
        sampleB = read_eval_log_sample(log_file, uuid=sampleA.uuid)
        assert sampleA.id == sampleB.id
        assert sampleA.epoch == sampleB.epoch
        assert sampleA.uuid == sampleB.uuid
        assert sampleA.input == sampleB.input


def test_read_sample_with_exclude_fields():
    eval_log_file = os.path.join(
        "tests", "log", "test_eval_log", "log_read_sample.eval"
    )
    sample = read_eval_log_sample(
        eval_log_file, id=1, epoch=1, exclude_fields={"store", "events"}
    )
    assert sample.id == 1
    assert sample.epoch == 1
    assert sample.input is not None
    assert not sample.store
    assert not sample.events


def test_log_location():
    json_log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    check_log_location(json_log_file)
    eval_log_file = os.path.join("tests", "log", "test_eval_log", "log_streaming.eval")
    check_log_location(eval_log_file)


def test_can_round_trip_serialize_model_event():
    original = ModelEvent(
        model="model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
        # Set timestamp to a timezone-aware datetime object because when serializing to
        # JSON, the datetime is converted to a timezone-aware string.
        # If we set the timestamp to a timezone-naive datetime object (default
        # behaviour), the deserialized object will have a timezone-aware datetime object
        # and the assert will fail.
        timestamp=datetime.now(timezone.utc),
    )

    serialized = original.model_dump_json()
    deserialized = ModelEvent.model_validate_json(serialized)

    assert original == deserialized


def _inject_invalid_unicode_into_log(log: EvalLog) -> EvalLog:
    # Ensure samples exist
    assert log.samples is not None and len(log.samples) > 0
    sample = log.samples[0]
    # Inject invalid surrogate into the model output content
    surrogate_input = "\udc00"
    sample.output = ModelOutput.from_content(
        model="mockllm/model",
        content=f"This is a surrogate: {surrogate_input}",
    )
    # Sanity check the invalid content is present in the in-memory object
    assert sample.output.choices[0].message.content == "This is a surrogate: \udc00"
    return log


def test_json_log_writer_handles_invalid_unicode_safely(tmp_path: str):
    # Read a valid log, mutate it to include invalid unicode in model output
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    log = read_eval_log(log_file)
    log = _inject_invalid_unicode_into_log(log)

    # Attempt to write as .json should raise due to unsafe serialization path
    out_path = os.path.join(tmp_path, "bad_unicode_log.json")
    write_eval_log(log, out_path)

    # Read the log back in
    roundtripped_log = read_eval_log(out_path)
    assert roundtripped_log.samples and len(roundtripped_log.samples) > 0
    assert (
        roundtripped_log.samples[0].output.choices[0].message.content
        == "This is a surrogate: \\udc00"
    )


def test_eval_log_writer_handles_invalid_unicode_safely(tmp_path: str):
    # Read a valid log, mutate it to include invalid unicode in model output
    log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.json")
    log = read_eval_log(log_file)
    log = _inject_invalid_unicode_into_log(log)

    # Attempt to write as .eval should raise due to unsafe serialization path
    out_path = os.path.join(tmp_path, "bad_unicode_log.eval")
    write_eval_log(log, out_path)

    # Read the log back in
    roundtripped_log = read_eval_log(out_path)
    assert roundtripped_log.samples and len(roundtripped_log.samples) > 0
    assert (
        roundtripped_log.samples[0].output.choices[0].message.content
        == "This is a surrogate: \\udc00"
    )


def test_can_round_trip_serialize_tool_event():
    original = ToolEvent(
        id="id", function="fn", arguments={}, timestamp=datetime.now(timezone.utc)
    )

    serialized = original.model_dump_json()
    deserialized = ToolEvent.model_validate_json(serialized)

    assert original == deserialized


def test_can_round_trip_serialize_tool_event_with_document_result():
    """ToolEvent round-trips document results through JSON serialization."""
    original = ToolEvent(
        id="id",
        function="fn",
        arguments={},
        result=[ContentDocument(document="/path/to/report.pdf")],
        timestamp=datetime.now(timezone.utc),
    )

    serialized = original.model_dump_json()
    deserialized = ToolEvent.model_validate_json(serialized)

    assert original == deserialized


def test_can_round_trip_serialize_sandbox_event():
    original = SandboxEvent(action="exec", timestamp=datetime.now(timezone.utc))

    serialized = original.model_dump_json()
    deserialized = SandboxEvent.model_validate_json(serialized)

    assert original == deserialized


def test_can_round_trip_serialize_subtask_event():
    original = SubtaskEvent(name="name", input={}, timestamp=datetime.now(timezone.utc))

    serialized = original.model_dump_json()
    deserialized = SubtaskEvent.model_validate_json(serialized)

    assert original == deserialized


def test_can_round_trip_serialize_score_edit_event():
    from inspect_ai.scorer._metric import ScoreEdit

    provenance = ProvenanceData(author="test_user", reason="Test edit")
    edit = ScoreEdit(value="I", provenance=provenance)
    original = ScoreEditEvent(
        score_name="test_scorer", edit=edit, timestamp=datetime.now(timezone.utc)
    )

    serialized = original.model_dump_json()
    deserialized = ScoreEditEvent.model_validate_json(serialized)

    assert original == deserialized


def test_can_load_log_with_all_tool_call_errors():
    # Log file contains all supported tool call errors.
    log_file = os.path.join("tests", "log", "test_eval_log", "log_tool_call_error.json")

    read_eval_log(log_file)


def test_log_provides_migrated_task_passed_args():
    log_file = os.path.join("tests", "log", "test_eval_log", "log_tool_call_error.json")
    log = read_eval_log(log_file)
    assert log.eval.task_args_passed == {"foo": "bar"}


def check_log_location(log_file: str):
    location = filesystem(log_file).info(log_file).name
    log = read_eval_log(location)
    assert log.location == location
    log = read_eval_log(location, header_only=True)
    assert log.location == location


def check_log_raises(log_file):
    with pytest.raises(ValueError):
        read_log(log_file)
    with pytest.raises(ValueError):
        read_log(log_file, header_only=True)


def test_unicode_surrogates_are_escaped():
    task = Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        solver=generate(),
        scorer=exact(),
    )

    [log] = eval(
        tasks=task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content(
                    model="mockllm/model",
                    content="\udc00\udc00\udc00",
                )
            ],
        ),
    )
    assert log.status == "success"
    sample = log.samples[0]
    assert sample.output.message.text == "\\udc00\\udc00\\udc00"
    assert sample.scores["exact"].answer == "\\udc00\\udc00\\udc00"


@pytest.mark.parametrize("resolve_attachments", [True, False, "full", "core"])
def test_message_deduplication(
    resolve_attachments: bool | Literal["full", "core"],
):
    log_file = os.path.join(
        "tests", "log", "test_eval_log", "log_message_deduplication.eval"
    )

    sample = read_eval_log_sample(
        log_file, id=0, epoch=1, resolve_attachments=resolve_attachments
    )

    # Messages appearing across multiple model event inputs should share
    # object identity (from the message pool). sample.messages is not
    # deduplicated against the pool since it reflects final state.
    messages_by_id = {}
    for event in sample.events:
        if isinstance(event, ModelEvent):
            for message in event.input:
                if message.id is None:
                    continue
                if message.id not in messages_by_id:
                    messages_by_id[message.id] = message
                else:
                    assert message is messages_by_id[message.id]


@pytest.mark.parametrize("format", ["json", "eval"])
def test_read_bytes_format(format):
    file_path = os.path.join("tests", "log", "test_eval_log", f"log_formats.{format}")

    log = read_eval_log(file_path)

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    bytesio = io.BytesIO(file_bytes)
    log2 = read_eval_log(bytesio, format=format)

    assert not log2.location
    assert log.eval.task == log2.eval.task
    assert log2.samples


@pytest.mark.parametrize("format", ["json", "eval"])
def test_read_bytes_format_detection(format):
    file_path = os.path.join("tests", "log", "test_eval_log", f"log_formats.{format}")

    log = read_eval_log(file_path)

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    bytesio = io.BytesIO(file_bytes)
    log2 = read_eval_log(bytesio, format="auto")

    assert log.eval.task == log2.eval.task
    assert log2.samples


@pytest.mark.parametrize("format", ["json", "eval"])
def test_read_bytes_header(format):
    file_path = os.path.join("tests", "log", "test_eval_log", f"log_formats.{format}")

    log = read_eval_log(file_path, header_only=True)

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    bytesio = io.BytesIO(file_bytes)
    log2 = read_eval_log(bytesio, header_only=True, format=format)

    assert log2.samples is None
    assert log.eval.task == log2.eval.task


list_logs_dir = os.path.join("tests", "log", "test_list_logs")


def test_progress_called_with_read_eval_log_headers():
    log_files = list_eval_logs(list_logs_dir, formats=["eval", "json"])

    class TrackingProgress(ReadEvalLogsProgress):
        def __init__(self) -> None:
            self.total: int | None = None
            self.read_files: list[str] = []

        @override
        def before_reading_logs(self, total_files: int) -> None:
            self.total = total_files

        @override
        def after_read_log(self, log_file: str) -> None:
            self.read_files.append(log_file)

    progress = TrackingProgress()
    headers = read_eval_log_headers(log_files, progress)

    assert progress.total == len(log_files)
    assert len(progress.read_files) == len(log_files)
    assert len(headers) == len(log_files)


# =============================================================================
# Tests that verify eval log reading works under the Trio backend.
#
# NOTE: We use anyio.run(backend="trio") directly rather than
# @pytest.mark.anyio because pytest-asyncio's asyncio_mode=auto
# intercepts the [trio] variant and runs it under asyncio, masking the bug.
# =============================================================================


def test_read_eval_log_header_trio():
    """Test reading .eval log header works under the Trio backend."""
    import anyio

    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai.log._file import read_eval_log_async

    eval_log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.eval")

    async def main() -> None:
        async with AsyncFilesystem():
            log = await read_eval_log_async(eval_log_file, header_only=True)

        assert log.eval is not None
        assert log.status is not None
        assert log.samples is None  # header_only

    anyio.run(main, backend="trio")


def test_read_eval_log_full_trio():
    """Test reading full .eval log works under the Trio backend."""
    import anyio

    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai.log._file import read_eval_log_async

    eval_log_file = os.path.join("tests", "log", "test_eval_log", "log_formats.eval")

    async def main() -> None:
        async with AsyncFilesystem():
            log = await read_eval_log_async(eval_log_file)

        assert log.eval is not None
        assert log.samples is not None
        assert len(log.samples) > 0

    anyio.run(main, backend="trio")


def test_read_eval_log_sample_trio():
    """Test reading a sample from .eval log works under the Trio backend."""
    import anyio

    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai.log._file import read_eval_log_sample_async

    eval_log_file = os.path.join(
        "tests", "log", "test_eval_log", "log_read_sample.eval"
    )

    async def main() -> None:
        async with AsyncFilesystem():
            sample = await read_eval_log_sample_async(eval_log_file, id=1, epoch=1)

        assert sample.id == 1
        assert sample.epoch == 1

    anyio.run(main, backend="trio")


# =============================================================================
# Tests for ZipLogFile flush cycles
# =============================================================================


@skip_if_trio
async def test_zip_log_file_flush_cycles() -> None:
    """Test that multiple flush cycles produce a valid .eval file."""
    from inspect_ai._util.constants import LOG_SCHEMA_VERSION
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalSample,
        EvalSpec,
    )
    from inspect_ai.log._recorders.eval import LogStart, ZipLogFile
    from inspect_ai.model._model_output import ModelOutput

    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path = os.path.join(temp_dir, "test.eval")

        eval_spec = EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task="test_task",
            model="mockllm/model",
            dataset=EvalDataset(name="test", samples=6),
            config=EvalConfig(),
        )
        plan = EvalPlan()
        log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

        zip_log = ZipLogFile(eval_path)
        await zip_log.init(log_start=None, summary_counter=0, summaries=[])
        await zip_log.start(log_start)

        # Write samples in 3 batches with flush between each
        all_sample_ids: list[int] = []
        for batch in range(3):
            for i in range(2):
                sample_id = batch * 2 + i + 1
                all_sample_ids.append(sample_id)
                sample = EvalSample(
                    id=sample_id,
                    epoch=1,
                    input=f"input {sample_id}",
                    target=f"target {sample_id}",
                    output=ModelOutput.from_content(
                        model="mockllm/model",
                        content=f"output {sample_id}",
                    ),
                    messages=[],
                )
                await zip_log.buffer_sample(sample)
            await zip_log.write_buffered_samples()
            await zip_log.flush()

        await zip_log.close(header_only=False)

        # Read back and verify
        log = read_eval_log(eval_path)
        assert log.eval.task == "test_task"
        assert log.samples is not None
        assert len(log.samples) == 6
        read_ids = sorted([s.id for s in log.samples])
        assert read_ids == all_sample_ids


# =============================================================================
# Tests for LazyList / lazy sample loading
# =============================================================================


@skip_if_trio
async def test_lazy_list_defers_loading() -> None:
    """Test that close(header_only=False) returns LazyList and defers loading."""
    from inspect_ai._util.constants import LOG_SCHEMA_VERSION
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalSample,
        EvalSpec,
    )
    from inspect_ai.log._recorders.eval import LazyList, LogStart, ZipLogFile
    from inspect_ai.model._model_output import ModelOutput

    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path = os.path.join(temp_dir, "test.eval")

        eval_spec = EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task="lazy_test",
            model="mockllm/model",
            dataset=EvalDataset(name="test", samples=4),
            config=EvalConfig(),
        )
        plan = EvalPlan()
        log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

        zip_log = ZipLogFile(eval_path)
        await zip_log.init(log_start=None, summary_counter=0, summaries=[])
        await zip_log.start(log_start)

        for i in range(1, 5):
            sample = EvalSample(
                id=i,
                epoch=1,
                input=f"input {i}",
                target=f"target {i}",
                output=ModelOutput.from_content(
                    model="mockllm/model",
                    content=f"output {i}",
                ),
                messages=[],
            )
            await zip_log.buffer_sample(sample)
        await zip_log.write_buffered_samples()
        await zip_log.flush()

        log = await zip_log.close(header_only=False)

        # Should be a LazyList instance (and also a list)
        assert isinstance(log.samples, LazyList)
        assert isinstance(log.samples, list)

        # The lazy data should not have been loaded yet
        lazy_data = log.samples._lazy_data
        assert lazy_data is not None
        assert not lazy_data.loaded

        # Accessing samples triggers loading
        assert len(log.samples) == 4
        assert lazy_data.loaded

        # Verify correct data
        sample_ids = sorted([s.id for s in log.samples])
        assert sample_ids == [1, 2, 3, 4]

    # Separate test block: model_dump() as the first access triggering lazy load
    with tempfile.TemporaryDirectory() as temp_dir2:
        from inspect_ai.log._recorders.eval import EvalRecorder

        eval_spec2 = EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task="lazy_dump_test",
            model="mockllm/model",
            dataset=EvalDataset(name="test", samples=4),
            config=EvalConfig(),
        )

        recorder = EvalRecorder(temp_dir2)
        await recorder.log_init(eval_spec2, clean=True)
        await recorder.log_start(eval_spec2, EvalPlan())

        for i in range(1, 5):
            sample = EvalSample(
                id=i,
                epoch=1,
                input=f"input {i}",
                target=f"target {i}",
                output=ModelOutput.from_content(
                    model="mockllm/model",
                    content=f"output {i}",
                ),
                messages=[],
            )
            await recorder.log_sample(eval_spec2, sample)

        from inspect_ai.log._log import EvalResults, EvalStats

        log2 = await recorder.log_finish(
            eval_spec2,
            status="success",
            stats=EvalStats(),
            results=EvalResults(),
            reductions=None,
        )

        assert isinstance(log2.samples, LazyList)
        assert not log2.samples._lazy_data.loaded
        # Reductions should be None since none were written
        assert log2.reductions is None
        # model_dump() should be the first and only trigger for lazy load
        dumped = log2.model_dump()
        assert dumped["samples"] is not None
        assert len(dumped["samples"]) == 4


@skip_if_trio
async def test_lazy_list_with_reductions() -> None:
    """Test that reductions are also lazily loaded."""
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalResults,
        EvalSample,
        EvalSampleReductions,
        EvalSpec,
        EvalStats,
    )
    from inspect_ai.log._recorders.eval import EvalRecorder, LazyList
    from inspect_ai.model._model_output import ModelOutput

    with tempfile.TemporaryDirectory() as temp_dir:
        eval_spec = EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task="lazy_reductions_test",
            model="mockllm/model",
            dataset=EvalDataset(name="test", samples=2),
            config=EvalConfig(),
        )

        recorder = EvalRecorder(temp_dir)
        await recorder.log_init(eval_spec, clean=True)
        await recorder.log_start(eval_spec, EvalPlan())

        for i in range(1, 3):
            sample = EvalSample(
                id=i,
                epoch=1,
                input=f"input {i}",
                target=f"target {i}",
                output=ModelOutput.from_content(
                    model="mockllm/model",
                    content=f"output {i}",
                ),
                messages=[],
            )
            await recorder.log_sample(eval_spec, sample)

        reductions = [
            EvalSampleReductions(
                scorer="test_scorer",
                samples=[],
            )
        ]

        log = await recorder.log_finish(
            eval_spec,
            status="success",
            stats=EvalStats(),
            results=EvalResults(),
            reductions=reductions,
        )

        # Both should be LazyList
        assert isinstance(log.samples, LazyList)
        assert isinstance(log.reductions, LazyList)

        # Access samples to trigger load
        assert len(log.samples) == 2
        # Reductions should also be loaded now (shared loader)
        assert len(log.reductions) == 1


@skip_if_trio
async def test_lazy_list_eq_triggers_load() -> None:
    """Test that __eq__ on an unloaded LazyList triggers loading."""
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalResults,
        EvalSample,
        EvalSpec,
        EvalStats,
    )
    from inspect_ai.log._recorders.eval import EvalRecorder, LazyList
    from inspect_ai.model._model_output import ModelOutput

    with tempfile.TemporaryDirectory() as temp_dir:
        eval_spec = EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task="lazy_eq_test",
            model="mockllm/model",
            dataset=EvalDataset(name="test", samples=2),
            config=EvalConfig(),
        )

        recorder = EvalRecorder(temp_dir)
        await recorder.log_init(eval_spec, clean=True)
        await recorder.log_start(eval_spec, EvalPlan())

        for i in range(1, 3):
            sample = EvalSample(
                id=i,
                epoch=1,
                input=f"input {i}",
                target=f"target {i}",
                output=ModelOutput.from_content(
                    model="mockllm/model",
                    content=f"output {i}",
                ),
                messages=[],
            )
            await recorder.log_sample(eval_spec, sample)

        log = await recorder.log_finish(
            eval_spec,
            status="success",
            stats=EvalStats(),
            results=EvalResults(),
            reductions=None,
        )

        assert isinstance(log.samples, LazyList)
        lazy_data = log.samples._lazy_data
        assert lazy_data is not None
        assert not lazy_data.loaded

        # Comparing with an empty list should trigger loading
        result = log.samples == []
        assert result is False
        assert lazy_data.loaded


@skip_if_trio
async def test_lazy_list_lazy_vs_lazy() -> None:
    """Test that __eq__ and __add__ between two LazyLists loads both sides."""
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalResults,
        EvalSample,
        EvalSpec,
        EvalStats,
    )
    from inspect_ai.log._recorders.eval import EvalRecorder, LazyList
    from inspect_ai.model._model_output import ModelOutput

    async def _make_lazy_log(
        temp_dir: str, task_name: str, sample_ids: list[int]
    ) -> EvalLog:
        eval_spec = EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task=task_name,
            model="mockllm/model",
            dataset=EvalDataset(name="test", samples=len(sample_ids)),
            config=EvalConfig(),
        )
        recorder = EvalRecorder(temp_dir)
        await recorder.log_init(eval_spec, clean=True)
        await recorder.log_start(eval_spec, EvalPlan())
        for i in sample_ids:
            sample = EvalSample(
                id=i,
                epoch=1,
                input=f"input {i}",
                target=f"target {i}",
                output=ModelOutput.from_content(
                    model="mockllm/model", content=f"output {i}"
                ),
                messages=[],
            )
            await recorder.log_sample(eval_spec, sample)
        return await recorder.log_finish(
            eval_spec,
            status="success",
            stats=EvalStats(),
            results=EvalResults(),
            reductions=None,
        )

    with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
        log_a = await _make_lazy_log(dir_a, "task_a", [1, 2])
        log_b = await _make_lazy_log(dir_b, "task_b", [1, 2])

        assert isinstance(log_a.samples, LazyList)
        assert isinstance(log_b.samples, LazyList)

        # Neither should be loaded yet
        lazy_a = log_a.samples._lazy_data
        lazy_b = log_b.samples._lazy_data
        assert lazy_a is not None and not lazy_a.loaded
        assert lazy_b is not None and not lazy_b.loaded

        # __eq__ should trigger loading on both sides (content differs, but
        # the important thing is that both sides get loaded)
        _ = log_a.samples == log_b.samples
        assert lazy_a.loaded
        assert lazy_b.loaded

    # Test __add__ with two fresh lazy lists
    with tempfile.TemporaryDirectory() as dir_c, tempfile.TemporaryDirectory() as dir_d:
        log_c = await _make_lazy_log(dir_c, "task_c", [1, 2])
        log_d = await _make_lazy_log(dir_d, "task_d", [3, 4])

        lazy_c = log_c.samples._lazy_data
        lazy_d = log_d.samples._lazy_data

        combined = log_c.samples + log_d.samples
        assert lazy_c.loaded
        assert lazy_d.loaded
        assert len(combined) == 4
        combined_ids = sorted([s.id for s in combined])
        assert combined_ids == [1, 2, 3, 4]

    # Test __radd__: regular_list + lazy_list
    with tempfile.TemporaryDirectory() as dir_e:
        log_e = await _make_lazy_log(dir_e, "task_e", [5, 6])
        lazy_e = log_e.samples._lazy_data
        assert not lazy_e.loaded

        result = [1, 2, 3] + log_e.samples
        assert lazy_e.loaded
        assert len(result) == 5


@skip_if_trio
async def test_lazy_list_header_only_no_lazy() -> None:
    """Test that close(header_only=True) does NOT use LazyList."""
    from inspect_ai._util.constants import LOG_SCHEMA_VERSION
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalPlan,
        EvalSample,
        EvalSpec,
    )
    from inspect_ai.log._recorders.eval import LazyList, LogStart, ZipLogFile
    from inspect_ai.model._model_output import ModelOutput

    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path = os.path.join(temp_dir, "test.eval")

        eval_spec = EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task="header_only_test",
            model="mockllm/model",
            dataset=EvalDataset(name="test", samples=2),
            config=EvalConfig(),
        )
        plan = EvalPlan()
        log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

        zip_log = ZipLogFile(eval_path)
        await zip_log.init(log_start=None, summary_counter=0, summaries=[])
        await zip_log.start(log_start)

        for i in range(1, 3):
            sample = EvalSample(
                id=i,
                epoch=1,
                input=f"input {i}",
                target=f"target {i}",
                output=ModelOutput.from_content(
                    model="mockllm/model",
                    content=f"output {i}",
                ),
                messages=[],
            )
            await zip_log.buffer_sample(sample)
        await zip_log.write_buffered_samples()
        await zip_log.flush()

        log = await zip_log.close(header_only=True)

        # header_only should have samples=None, not a LazyList
        assert log.samples is None
        assert not isinstance(log.samples, LazyList)


# =============================================================================
# Tests for log_files_from_ls sort key
# =============================================================================


def test_log_files_from_ls_sort_order():
    """Test sort order with mixed and None mtime values."""
    files = [
        FileInfo(name="2024-01-01T00:00:00.eval", type="file", size=100, mtime=300.0),
        FileInfo(name="2024-01-02T00:00:00.eval", type="file", size=100, mtime=100.0),
        FileInfo(name="2024-01-03T00:00:00.eval", type="file", size=100, mtime=None),
        FileInfo(name="2024-01-04T00:00:00.eval", type="file", size=100, mtime=200.0),
    ]

    # Descending: highest mtime first, None (treated as 0) last
    desc = log_files_from_ls(files, descending=True)
    desc_mtimes = [
        300.0,  # mtime=300
        200.0,  # mtime=200
        100.0,  # mtime=100
        None,  # mtime=None (sorts as 0)
    ]
    assert [f.mtime for f in desc] == desc_mtimes

    # Ascending: None (treated as 0) first, then lowest mtime
    asc = log_files_from_ls(files, descending=False)
    asc_mtimes = [
        None,  # mtime=None (sorts as 0)
        100.0,  # mtime=100
        200.0,  # mtime=200
        300.0,  # mtime=300
    ]
    assert [f.mtime for f in asc] == asc_mtimes


def test_eval_sample_timeline_round_trip():
    """EvalSample with timelines can round-trip through serialization.

    Timeline events are serialized as UUID strings. Deserialization must
    resolve those UUIDs back to Event objects using the sample's events.
    """
    now = datetime.now(timezone.utc)
    events = [
        SpanBeginEvent(id="span1", name="test_span", timestamp=now),
        InfoEvent(data="hello", timestamp=now),
        SpanEndEvent(id="span1", timestamp=now),
    ]

    timeline = timeline_build(events)

    sample = EvalSample(
        id=1,
        epoch=1,
        input="test input",
        target="test target",
        events=events,
        timelines=[timeline],
    )

    # Serialize — timeline event refs become UUID strings
    data = sample.model_dump()

    # Deserialize — should resolve UUID strings back to Event objects
    restored = EvalSample.model_validate(data, context=get_deserializing_context())

    assert restored.timelines is not None
    assert len(restored.timelines) == 1
    assert restored.timelines[0].name == timeline.name

    # Walk timeline content and verify events are resolved (not UUID strings)
    def find_timeline_events(content: list) -> list[TimelineEvent]:
        result = []
        for item in content:
            if isinstance(item, TimelineEvent):
                result.append(item)
            elif hasattr(item, "content"):
                result.extend(find_timeline_events(item.content))
        return result

    timeline_events = find_timeline_events(restored.timelines[0].root.content)
    assert len(timeline_events) > 0
    for te in timeline_events:
        # event should be an Event object, not a string
        assert not isinstance(te.event, str)
        assert te.event.uuid is not None
