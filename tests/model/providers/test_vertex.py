import pytest
from test_helpers.utils import skip_if_no_vertex

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.scorer import includes


@pytest.mark.asyncio
@skip_if_no_vertex
async def test_vertex_api() -> None:
    model = get_model(
        "vertex/gemini-1.5-flash",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            logit_bias=dict([(42, 10), (43, -10)]),
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


@skip_if_no_vertex
def test_vertex_safety_settings():
    safety_settings = dict(
        dangerous_content="medium_and_above",
        hate_speech="low_and_above",
        unspecified="low_and_above",
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
        model="vertex/gemini-1.5-flash",
        safety_settings=safety_settings,
    )
