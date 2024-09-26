from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import Solver, generate, prompt_template, system_message

PROMPT_TEMPLATE = """
Please answer this question.

{param}

{variable}

{prompt}
"""

PARAM_VALUE = "param_value"
VARIABLE_VALUE = "variable_value"
PROMPT_VALUE = "prompt_value"


def check_template_variables(solver: Solver):
    task = Task(
        dataset=[
            Sample(
                input="Say hello.",
                target="Hello",
                metadata=dict(variable=VARIABLE_VALUE, prompt=PROMPT_VALUE),
            )
        ],
        solver=[solver, generate()],
    )

    log = eval(task, model="mockllm/model")[0]
    assert log.samples
    message = log.samples[0].messages[0].text

    assert VARIABLE_VALUE in message
    assert PARAM_VALUE in message

    return message


def test_prompt_template_variables():
    message = check_template_variables(
        prompt_template(PROMPT_TEMPLATE, param=PARAM_VALUE)
    )
    assert PROMPT_VALUE not in message


def test_system_message_variables():
    check_template_variables(system_message(PROMPT_TEMPLATE, param=PARAM_VALUE))
