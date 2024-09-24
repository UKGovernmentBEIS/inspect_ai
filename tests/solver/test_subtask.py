# does get_model actually use the default task generate config?
# does it successfully override?

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, TaskState, generate, solver
from inspect_ai.util._store import store
from inspect_ai.util._subtask import subtask


@subtask
async def times_two(input: int) -> int:
    assert store().get("x", 0) == 0
    store().set("x", 84)
    return input * 2


def test_subtask():
    @solver
    def subtask_solver():
        async def solve(state: TaskState, generate: Generate):
            state.store.set("x", 42)
            # call twice so times_two can verify that state is reset
            result = await times_two(int(state.input_text))
            result = await times_two(int(state.input_text))
            state.output = ModelOutput.from_content(state.model.name, str(result))
            return state

        return solve

    task = Task(
        dataset=[
            Sample(input="1", target="2"),
        ],
        solver=[generate(), subtask_solver()],
        scorer=match(),
    )

    log = eval(task, model="mockllm/model")[0]
    assert log.samples[0].store.get("x") == 42
    assert log.samples[0].output.completion == "2"
