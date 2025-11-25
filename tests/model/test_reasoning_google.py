from test_helpers.utils import skip_if_no_google

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog


@skip_if_no_google
def test_google_reasoning_tokens():
    # run eval w/ reasoning tokens
    task = Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")])
    log = eval(
        task,
        model="google/gemini-2.5-flash",
        reasoning_tokens=1024,
    )[0]
    assert log.status == "success"

    # confirm thinking budget was set and reasoning was done
    log_json = log.model_dump_json(indent=2)
    assert '"thinkingBudget": 1024' in log_json

    check_for_reasoning(log)


@skip_if_no_google
def test_google_reasoning_effort():
    # run eval w/ reasoning tokens
    task = Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")])
    log = eval(
        task,
        model="google/gemini-3-pro-preview",
        reasoning_effort="low",
    )[0]
    assert log.status == "success"

    # confirm thinking budget was set and reasoning was done
    log_json = log.model_dump_json(indent=2)
    assert '"thinkingLevel": "LOW"' in log_json

    check_for_reasoning(log)


def check_for_reasoning(log: EvalLog) -> None:
    assert log.samples
    output = log.samples[0].output
    assert output.usage
    assert output.usage.reasoning_tokens

    # confirm we captured the reasoning content block
    content = output.message.content
    if isinstance(content, ContentReasoning):
        pass
    elif isinstance(content, list):
        assert any(isinstance(item, ContentReasoning) for item in content), (
            "List should contain at least one ContentReasoning object"
        )
    else:
        assert False, f"Content should be ContentReasoning or list, got {type(content)}"
