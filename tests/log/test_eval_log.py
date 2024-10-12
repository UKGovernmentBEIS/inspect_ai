import math
import os

import pytest
from pydantic_core import PydanticSerializationError

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.solver import (
    Generate,
    TaskState,
    generate,
    solver,
)


def log_path(file: str) -> str:
    # use .txt extension so vscode linter doesn't complain about invalid json
    return os.path.join("tests", "log", "test_eval_log", f"{file}.txt")


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
    check_for_nan(read_eval_log(log_file))
    check_for_nan(read_eval_log(log_file, header_only=True))


def test_fail_invalid():
    check_log_raises(log_path("log_invalid"))


def test_fail_version():
    check_log_raises(log_path("log_version_3"))


def test_valid_log_header():
    log = read_eval_log(log_path("log_valid"), header_only=True)
    assert log.eval.metadata["meaning_of_life"] == 42


def test_migrate_length_stop_reason():
    log = read_eval_log(log_path("log_length_stop_reason"))
    assert log.samples[0].output.stop_reason == "max_tokens"


def check_log_raises(log_file):
    with pytest.raises(ValueError):
        read_eval_log(log_file)
    with pytest.raises(ValueError):
        read_eval_log(log_file, header_only=True)
