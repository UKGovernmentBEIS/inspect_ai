from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import Solver, generate, prompt_template, solver, system_message
from inspect_ai.solver._prompt import assistant_message, user_message
from inspect_ai.solver._solver import Generate
from inspect_ai.solver._task_state import TaskState

PROMPT_TEMPLATE = """
Please answer this question.

{param}

{variable}

{prompt}

{unknown}

{{escaped}}
"""

PARAM_VALUE = "param_value"
VARIABLE_VALUE = "variable_value"
PROMPT_VALUE = "prompt_value"


def check_template_variables(template_solver: Solver, index: int = 0):
    @solver
    def set_store_var(name: str, value: str) -> Solver:
        async def solve(state: TaskState, generate: Generate):
            state.store.set(name, value)
            return state

        return solve

    task = Task(
        dataset=[
            Sample(
                input="Say hello.",
                target="Hello",
                metadata=dict(prompt=PROMPT_VALUE),
            )
        ],
        solver=[set_store_var("variable", VARIABLE_VALUE), template_solver, generate()],
    )

    log = eval(task, model="mockllm/model")[0]
    assert log.samples
    message = log.samples[0].messages[index].text

    assert VARIABLE_VALUE in message
    assert PARAM_VALUE in message
    assert "{unknown}" in message
    assert "{escaped}" in message

    return message


def test_prompt_template_variables():
    message = check_template_variables(
        prompt_template(PROMPT_TEMPLATE, param=PARAM_VALUE)
    )
    assert PROMPT_VALUE not in message


def test_system_message_variables():
    check_template_variables(system_message(PROMPT_TEMPLATE, param=PARAM_VALUE))


def test_user_message_variables():
    check_template_variables(user_message(PROMPT_TEMPLATE, param=PARAM_VALUE), index=-2)


@skip_if_no_openai
def test_user_and_assistant_message():
    ASSISTANT_MESSAGE = "Did you mean 'hello' or 'hello, world'?"
    task = Task(
        dataset=[Sample(input="Say hello.", target="hello")],
        solver=[
            assistant_message(ASSISTANT_MESSAGE),
            user_message("I meant 'hello'"),
        ],
    )
    log = eval(task, model="openai/gpt-4o-mini")[0]
    assert log.status == "success"
    assert log.samples
    assert log.samples[0].messages[1].text == ASSISTANT_MESSAGE
