from test_helpers.utils import skip_if_no_google

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample


@skip_if_no_google
def test_google_reasoning_tokens():
    task = Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")])
    log = eval(
        task,
        model="google/gemini-2.5-flash-preview-04-17",
        reasoning_tokens=1024,
    )[0]
    assert log.status == "success"
    log_json = log.model_dump_json(indent=2)
    assert '"thinkingBudget": 1024' in log_json
    assert log.samples
    assert log.samples[0].output.usage.reasoning_tokens > 0
