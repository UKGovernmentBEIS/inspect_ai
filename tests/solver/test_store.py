from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes, match
from inspect_ai.solver import Generate, TaskState, generate, solver, store, use_tools
from inspect_ai.tool import tool


def test_sample_store():
    @solver
    def store_solver():
        async def solve(state: TaskState, generate: Generate):
            state.store.set("data", state.sample_id)
            return state

        return solve

    task = Task(
        dataset=[
            Sample(input="Say Hello", target="Hello"),
            Sample(input="Say Goodbye", target="Goodbye"),
        ],
        plan=[store_solver(), generate()],
        scorer=match(),
    )

    log = eval(task, model="mockllm/model")[0]
    assert log.samples[0].store["data"] == 1
    assert log.samples[1].store["data"] == 2


@skip_if_no_openai
def test_tool_store():
    @tool(prompt="If you are asked to get a cookie, call the get_cookie function.")
    def get_cookie():
        async def exec():
            """
            Tool for getting the cookie.

            Returns: The cookie.
            """
            return store().get("cookie", 0)

        return exec

    @solver
    def store_solver():
        async def solve(state: TaskState, generate: Generate):
            state.store.set("cookie", 42)
            return state

        return solve

    task = Task(
        dataset=[
            Sample(input="Get the cookie using the available tools.", target="42"),
        ],
        plan=[use_tools(get_cookie()), store_solver(), generate()],
        scorer=includes(),
    )

    log = eval(task, model="openai/gpt-4-turbo")[0]
    assert log.results.metrics["accuracy"].value == 1
