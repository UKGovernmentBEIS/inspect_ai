import math
import os
import tempfile
from datetime import datetime, timezone

import pytest
from pydantic_core import PydanticSerializationError

from inspect_ai import Task, eval
from inspect_ai._util.file import filesystem
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.log._file import read_eval_log_sample, write_eval_log
from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import (
    ModelEvent,
    SandboxEvent,
    SubtaskEvent,
    ToolEvent,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
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


def test_can_round_trip_serialize_tool_event():
    original = ToolEvent(
        id="id", function="fn", arguments={}, timestamp=datetime.now(timezone.utc)
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
