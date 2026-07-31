from typing import Any, Literal, cast

import pytest
from test_helpers.utils import (
    skip_if_no_cloudflare,
    skip_if_no_groq,
    skip_if_no_moonshot,
    skip_if_no_openai,
    skip_if_no_openrouter,
    skip_if_no_together,
)

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentBase, ContentReasoning
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model
from inspect_ai.solver._prompt import user_message
from inspect_ai.solver._solver import generate
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_choice import ToolChoice


@skip_if_no_together
async def test_reasoning_content_together():
    await check_reasoning_content("together/openai/gpt-oss-20b")


@skip_if_no_groq
async def test_reasoning_content_groq():
    await check_reasoning_content("groq/openai/gpt-oss-20b")


@skip_if_no_openai
async def test_reasoning_content_openai():
    await check_reasoning_content("openai/gpt-5-mini")


@skip_if_no_openai
@skip_if_no_openrouter
async def test_reasoning_content_openrouter_openai():
    await check_reasoning_content("openrouter/openai/o4-mini")


def check_reasoning_round_trip(model: str) -> None:
    """Reasoning round trip.

    Verifies reasoning is parsed from responses AND replayed back to the
    model in the raw request payload under the same field it was received
    in (e.g. reasoning_content), on prior assistant messages.
    """
    task = Task(
        dataset=[Sample(input="Solve 3*x^3-5*x=1")],
        solver=[
            generate(),
            user_message("Great! Now explain what you just did."),
            generate(),
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.samples
    sample = resolve_sample_attachments(log.samples[0])
    model_events = [event for event in sample.events if event.event == "model"]

    # reasoning was parsed from the response (internal records its source field)
    first_content = model_events[0].output.choices[0].message.content
    assert isinstance(first_content, list)
    reasoning = [c for c in first_content if isinstance(c, ContentReasoning)]
    assert reasoning
    source_field = str(reasoning[0].internal)
    assert source_field in ("reasoning", "reasoning_content")

    # reasoning was replayed in the raw request under the same field
    assert model_events[-1].call is not None
    request_messages = cast(
        list[dict[str, Any]], model_events[-1].call.request["messages"]
    )
    replayed = [
        message
        for message in request_messages
        if message["role"] == "assistant" and message.get(source_field)
    ]
    assert replayed


@pytest.mark.slow
@skip_if_no_cloudflare
@pytest.mark.parametrize(
    "model",
    [
        # native model (returns reasoning in the 'reasoning' field)
        "cloudflare/@cf/google/gemma-4-26b-a4b-it",
        # gateway model (returns reasoning in the 'reasoning_content' field)
        "cloudflare/moonshotai/kimi-k3",
    ],
)
def test_reasoning_content_cloudflare(model: str):
    check_reasoning_round_trip(model)


@pytest.mark.slow
@skip_if_no_moonshot
def test_reasoning_content_moonshot():
    check_reasoning_round_trip("moonshot/kimi-k3")


@pytest.mark.slow
@skip_if_no_together
def test_reasoning_history_none():
    check_reasoning_history("none", 0)


@pytest.mark.slow
@skip_if_no_together
def test_reasoning_history_all():
    check_reasoning_history("all", 2)


@pytest.mark.slow
@skip_if_no_together
def test_reasoning_history_last():
    check_reasoning_history("last", 1)


async def check_reasoning_content(
    model_name: str,
    config: GenerateConfig = GenerateConfig(),
    tools: list[Tool] = [],
    tool_choice: ToolChoice | None = None,
    reasoning_tokens: int | None = 1024,
):
    model = get_model(model_name)
    output = await model.generate(
        "Solve 3*x^3-5*x=1",
        config=config.merge(
            GenerateConfig(
                reasoning_effort="low",
                reasoning_tokens=reasoning_tokens,
                max_tokens=8192,
            )
        ),
        tools=tools,
        tool_choice=tool_choice,
    )
    assert "<think>" not in output.completion
    content = output.choices[0].message.content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentReasoning)


def check_reasoning_history(
    reasoning_history: Literal["none", "all", "last"], expected_thinking_blocks: int
):
    task = Task(
        dataset=[Sample(input="Please say hello, world")],
        solver=[
            generate(),
            user_message("Great!, now say 'goodbye, world'"),
            generate(),
            user_message("Great!, Now explain what you just did."),
            generate(),
        ],
    )

    log = eval(
        task,
        model="together/deepseek-ai/DeepSeek-R1",
        reasoning_history=reasoning_history,
    )[0]
    assert log.samples
    sample = resolve_sample_attachments(log.samples[0])
    last_model_event = [event for event in sample.events if event.event == "model"][-1]

    # count thinking in payload sent to server
    thinking_blocks = sum(
        1
        for message in last_model_event.input
        if any(
            [
                c.type == "reasoning"
                for c in message.content
                if isinstance(c, ContentBase)
            ]
        )
    )
    assert thinking_blocks == expected_thinking_blocks
