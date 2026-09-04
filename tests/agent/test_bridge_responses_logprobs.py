"""Unit tests for Responses logprob passthrough in the agent bridge.

A Responses client asks for logprobs with `include:
["message.output_text.logprobs"]`. The bridge maps that onto
`GenerateConfig.logprobs`, so the resolved model can populate
`ChatCompletionChoice.logprobs` — but the response builder used to rebuild every
`ResponseOutputText` with `logprobs=[]`, so the client never saw them and
downstream scorers silently fell back to their missing-logprobs path (#5211).

The logprobs describe one generated token sequence, so they attach to the first
genuine `output_text` block only: not to reasoning think tags, not to refusals,
and never to a second text block.
"""

from __future__ import annotations

from openai import AsyncOpenAI
from openai.types.responses import Response, ResponseOutputItem, ResponseOutputText
from openai.types.responses.response_output_text import (
    Logprob as LogprobResponses,
)
from test_helpers.utils import skip_if_no_openai_package

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.agent._bridge.responses_impl import (
    responses_output_items_from_assistant_message,
)
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageAssistant, ModelOutput, get_model
from inspect_ai.model._model_output import Logprob, Logprobs, TopLogprob
from inspect_ai.scorer import includes

ANSWER = "hi"


def logprobs_fixture() -> Logprobs:
    return Logprobs(
        content=[
            Logprob(
                token="hi",
                logprob=-0.1,
                bytes=[104, 105],
                top_logprobs=[
                    TopLogprob(token="hi", logprob=-0.1, bytes=[104, 105]),
                    TopLogprob(token="hey", logprob=-2.3, bytes=[104, 101, 121]),
                ],
            )
        ]
    )


def output_texts(items: list[ResponseOutputItem]) -> list[ResponseOutputText]:
    return [
        content
        for item in items
        if item.type == "message"
        for content in item.content
        if content.type == "output_text"
    ]


def text_logprobs(text: ResponseOutputText) -> list[LogprobResponses]:
    assert text.logprobs is not None
    return text.logprobs


def test_output_text_carries_choice_logprobs() -> None:
    message = ChatMessageAssistant(content=ANSWER)

    items = responses_output_items_from_assistant_message(
        message, logprobs=logprobs_fixture()
    )

    texts = output_texts(items)
    assert len(texts) == 1
    logprobs = text_logprobs(texts[0])
    assert len(logprobs) == 1
    assert logprobs[0].token == "hi"
    assert logprobs[0].logprob == -0.1
    assert logprobs[0].bytes == [104, 105]
    assert [(t.token, t.logprob, t.bytes) for t in logprobs[0].top_logprobs] == [
        ("hi", -0.1, [104, 105]),
        ("hey", -2.3, [104, 101, 121]),
    ]


def test_output_text_has_no_logprobs_when_choice_has_none() -> None:
    message = ChatMessageAssistant(content=ANSWER)

    items = responses_output_items_from_assistant_message(message)

    assert output_texts(items)[0].logprobs == []


def test_empty_choice_logprobs_leave_output_text_empty() -> None:
    message = ChatMessageAssistant(content=ANSWER)

    items = responses_output_items_from_assistant_message(
        message, logprobs=Logprobs(content=[])
    )

    assert output_texts(items)[0].logprobs == []


def test_absent_bytes_and_top_logprobs_become_empty_lists() -> None:
    message = ChatMessageAssistant(content=ANSWER)
    logprobs = Logprobs(content=[Logprob(token="hi", logprob=-0.1)])

    items = responses_output_items_from_assistant_message(message, logprobs=logprobs)

    converted = text_logprobs(output_texts(items)[0])
    assert converted[0].bytes == []
    assert converted[0].top_logprobs == []


def test_reasoning_block_does_not_carry_logprobs() -> None:
    message = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="thinking"), ContentText(text=ANSWER)]
    )

    items = responses_output_items_from_assistant_message(
        message, logprobs=logprobs_fixture()
    )

    texts = output_texts(items)
    assert len(texts) == 2
    assert texts[0].logprobs == []
    assert texts[1].text == ANSWER
    assert len(text_logprobs(texts[1])) == 1


def test_logprobs_attach_to_only_the_first_text_block() -> None:
    message = ChatMessageAssistant(
        content=[ContentText(text=ANSWER), ContentText(text="there")]
    )

    items = responses_output_items_from_assistant_message(
        message, logprobs=logprobs_fixture()
    )

    texts = output_texts(items)
    assert len(texts) == 2
    assert len(text_logprobs(texts[0])) == 1
    assert texts[1].logprobs == []


def test_refusal_does_not_consume_logprobs() -> None:
    message = ChatMessageAssistant(
        content=[
            ContentText(text="i cannot help with that", refusal=True),
            ContentText(text=ANSWER),
        ]
    )

    items = responses_output_items_from_assistant_message(
        message, logprobs=logprobs_fixture()
    )

    refusals = [
        content
        for item in items
        if item.type == "message"
        for content in item.content
        if content.type == "refusal"
    ]
    assert len(refusals) == 1

    texts = output_texts(items)
    assert len(texts) == 1
    assert texts[0].text == ANSWER
    assert len(text_logprobs(texts[0])) == 1


@agent
def logprobs_agent() -> Agent:
    """Bridge agent asserting a Responses client receives the host model's logprobs."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state, forward_generation_config=True) as bridge:
            async with AsyncOpenAI(api_key="test") as client:
                response = await client.responses.create(
                    model="inspect",
                    input="hello",
                    include=["message.output_text.logprobs"],
                    top_logprobs=2,
                )
                assert isinstance(response, Response)
                texts = output_texts(list(response.output))
                assert len(texts) == 1
                logprobs = text_logprobs(texts[0])
                assert [lp.token for lp in logprobs] == ["hi"]
                assert logprobs[0].bytes == [104, 105]
                assert [t.token for t in logprobs[0].top_logprobs] == ["hi", "hey"]
            return bridge.state

    return execute


@skip_if_no_openai_package
def test_bridge_returns_logprobs_to_responses_client() -> None:
    model_output = ModelOutput.from_content("mockllm/model", ANSWER)
    model_output.choices[0].logprobs = logprobs_fixture()

    task = Task(
        dataset=[Sample(input="hello", target="done")],
        solver=logprobs_agent(),
        scorer=includes(),
    )
    log = eval(task, model=get_model("mockllm/model", custom_outputs=[model_output]))[0]

    assert log.status == "success", (
        log.error.message if log.error else "eval did not succeed"
    )
