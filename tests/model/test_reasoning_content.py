from typing import Literal

import pytest
from test_helpers.utils import (
    skip_if_no_groq,
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


@pytest.mark.anyio
@skip_if_no_together
async def test_reasoning_content_together():
    await check_reasoning_content("together/Qwen/Qwen3-235B-A22B-Thinking-2507")


@pytest.mark.anyio
@skip_if_no_groq
async def test_reasoning_content_groq():
    await check_reasoning_content("groq/deepseek-r1-distill-llama-70b")


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
    model_name: str, config: GenerateConfig = GenerateConfig()
):
    model = get_model(model_name)
    output = await model.generate(
        "Please say 'hello, world'",
        config=config.merge(
            GenerateConfig(reasoning_effort="low", reasoning_tokens=1024)
        ),
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
