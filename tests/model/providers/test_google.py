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

    # note: the log doesn't currently have evidence
    # that the safety settings are successfully passed
    # to google, but to the extent we know they are,
    # this tests whether they are correctly mapped to
    # the requisite enum values and that the google
    # api accepts them without error
    eval(
        Task(
            dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
            scorer=includes(),
        ),
        model="google/gemini-1.5-flash",
        model_args=dict(safety_settings=safety_settings),
    )


@skip_if_no_google
def test_google_block_reason():
    safety_settings = dict(harassment="low")
    log = eval(
        Task(
            # TODO: we can't seem to get a harrassement filter to trigger!
            dataset=[Sample(input="you are a shameful model")],
            scorer=includes(),
        ),
        model="google/gemini-2.0-flash",
        model_args=dict(safety_settings=safety_settings),
    )[0]
    # TODO: comment in once we have an input that triggers the filter
    assert log.samples
    assert log.samples[0].output.stop_reason == "content_filter"
