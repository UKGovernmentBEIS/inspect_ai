from test_helpers.utils import skip_if_no_google

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes


@skip_if_no_google
def test_google_safety_settings():
    safety_settings = dict(
        dangerous_content="medium_and_above",
        hate_speech="low_and_above",
    )

    # run with safety settings
    log = eval(
        Task(
            dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
            scorer=includes(),
        ),
        model="google/gemini-1.5-flash",
        model_args=dict(safety_settings=safety_settings),
    )[0]
    log_json = log.model_dump_json(indent=2)
    assert '"HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_MEDIUM_AND_ABOVE"' in log_json
    assert '"HARM_CATEGORY_HATE_SPEECH": "BLOCK_LOW_AND_ABOVE"' in log_json
    assert '"HARM_CATEGORY_HARASSMENT": "BLOCK_NONE"' in log_json


@skip_if_no_google
def test_google_block_reason():
    safety_settings = dict(harassment="low")
    eval(
        Task(
            # TODO: we can't seem to get a content filter to trigger!
            dataset=[Sample(input="you are a shameful model")],
        ),
        model="google/gemini-2.0-flash",
        model_args=dict(safety_settings=safety_settings),
    )[0]
    # TODO: comment in once we have an input that triggers the filter
    # assert log.samples
    # assert log.samples[0].output.stop_reason == "content_filter"


@skip_if_no_google
def test_google_reasoning_content():
    log = eval(
        Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")]),
        model="google/gemini-2.0-flash-thinking-exp",
    )[0]
    assert log.samples
    assert log.samples[0].output.message.reasoning
