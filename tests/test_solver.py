from utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser, ModelOutput, get_model
from inspect_ai.scorer import match
from inspect_ai.solver import (
    Generate,
    Plan,
    TaskState,
    chain_of_thought,
    generate,
    solver,
)


@skip_if_no_openai
def test_solvers_termination():
    @solver
    def user_input(input: str):
        async def solve(state: TaskState, generate: Generate):
            state.messages.append(ChatMessageUser(content=input))
            return state

        return solve

    @solver
    def complete_task():
        async def solve(state: TaskState, generate: Generate):
            state.completed = True
            return state

        return solve

    @solver
    def finish():
        async def solve(state: TaskState, generate: Generate):
            state.output = ModelOutput.from_content(
                model="openai/gpt-4", content="finished"
            )
            return state

        return solve

    model = get_model("openai/gpt-4")
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        plan=Plan(
            steps=[
                chain_of_thought(),
                generate(),
                user_input("How about multiplying the numbers?"),
                generate(),
                complete_task(),
                user_input("How about subtracting the numbers?"),
                generate(),
            ],
            finish=finish(),
        ),
        scorer=match(),
    )

    log = eval(task, model=model)[0]
    assert len(log.samples[0].messages) == 4
    assert log.samples[0].output.completion == "finished"

    log = eval(task, model=model, max_messages=2)[0]
    assert len(log.samples[0].messages) == 2
    assert log.samples[0].output.completion == "finished"
