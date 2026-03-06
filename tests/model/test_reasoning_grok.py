from test_helpers.utils import skip_if_no_grok

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning
from inspect_ai.dataset import Sample


@skip_if_no_grok
def test_grok_reasoning_effort_and_output():
    task = Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")])
    log = eval(
        task,
        model="grok/grok-3-mini",
        reasoning_effort="low",
    )[0]
    assert log.status == "success"
    assert log.samples
    assert isinstance(log.samples[0].messages[-1].content[0], ContentReasoning)
    assert log.samples[0].output.usage.reasoning_tokens > 0
