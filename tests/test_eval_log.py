from pydantic_core import PydanticSerializationError
from utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import (
    Generate,
    Plan,
    TaskState,
    generate,
    solver,
)


class NotSerializable:
    name: str


@skip_if_no_openai
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
        eval(task, model="openai/gpt-4")
    except PydanticSerializationError:
        assert False, "Eval raised Pydantic serialization error."
