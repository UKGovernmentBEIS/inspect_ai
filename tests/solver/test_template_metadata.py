from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate, prompt_template

PROMPT_TEMPLATE = """
Please answer this question.

{variable}

{prompt}
"""


def test_prompt_template_metadata():
    VARIABLE_VALUE = "variable_value"
    PROMPT_VALUE = "prompt_value"

    task = Task(
        dataset=[
            Sample(
                input="Say hello.",
                target="Hello",
                metadata=dict(variable=VARIABLE_VALUE, prompt=PROMPT_VALUE),
            )
        ],
        plan=[prompt_template(PROMPT_TEMPLATE), generate()],
    )

    log = eval(task, model="mockllm/model")[0]
    message = log.samples[0].messages[0].text

    assert VARIABLE_VALUE in message
    assert PROMPT_VALUE not in message
