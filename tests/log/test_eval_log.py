import math
import os

import pytest
from pydantic_core import PydanticSerializationError

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.solver import (
    Generate,
    Plan,
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
        plan=Plan(steps=[inject_unserializable(), generate()]),
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
    check_log_raises(log_path("log_version_2"))


def check_log_raises(log_file):
    with pytest.raises(ValueError):
        read_eval_log(log_file)
    with pytest.raises(ValueError):
        read_eval_log(log_file, header_only=True)
