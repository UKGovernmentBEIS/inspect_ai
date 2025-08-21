from typing import Literal

import pytest
from test_helpers.utils import (
    skip_if_no_groq,
    skip_if_no_openai,
    skip_if_no_openrouter,
    skip_if_no_together,
)

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model
from inspect_ai.solver._prompt import user_message
from inspect_ai.solver._solver import generate
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_choice import ToolChoice


@pytest.mark.asyncio
@skip_if_no_together
async def test_reasoning_content_together():
    await check_reasoning_content("together/openai/gpt-oss-20b")


@pytest.mark.asyncio
@skip_if_no_groq
async def test_reasoning_content_groq():
    await check_reasoning_content("groq/openai/gpt-oss-20b")


@pytest.mark.asyncio
@skip_if_no_openai
async def test_reasoning_content_openai():
    await check_reasoning_content("openai/o4-mini")


@pytest.mark.asyncio
@skip_if_no_openai
@skip_if_no_openrouter
async def test_reasoning_content_openrouter_openai():
    await check_reasoning_content("openrouter/openai/o4-mini")


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
):
    model = get_model(model_name)
    output = await model.generate(
        "Solve 3*x^3-5*x=1",
        config=config.merge(
            GenerateConfig(
                reasoning_effort="low", reasoning_tokens=1024, max_tokens=8192
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
        1 for message in last_model_event.input if "<think>" in message.text
    )
    assert thinking_blocks == expected_thinking_blocks
