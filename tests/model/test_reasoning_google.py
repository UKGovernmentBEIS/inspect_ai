from test_helpers.utils import skip_if_no_google

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning
from inspect_ai.dataset import Sample


@skip_if_no_google
def test_google_reasoning():
    # run eval w/ reasoning tokens
    task = Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")])
    log = eval(
        task,
        model="google/gemini-2.5-flash-preview-05-20",
        reasoning_tokens=1024,
    )[0]
    assert log.status == "success"

    # confirm thinking budget was set and reasoning was done
    log_json = log.model_dump_json(indent=2)
    assert '"thinkingBudget": 1024' in log_json
    assert log.samples
    output = log.samples[0].output
    assert output.usage.reasoning_tokens > 0

    # confirm we captured the reasoning content block
    content = output.message.content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentReasoning)
