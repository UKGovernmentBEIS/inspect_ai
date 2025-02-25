import pytest
from test_helpers.utils import skip_if_no_google, skip_if_no_groq, skip_if_no_together

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model
from inspect_ai.solver._prompt import user_message
from inspect_ai.solver._solver import generate


async def check_reasoning_content(model_name: str):
    model = get_model(model_name)
    output = await model.generate(
        "Please say 'hello, world'", config=GenerateConfig(reasoning_effort="low")
    )
    assert "<think>" not in output.completion
    content = output.choices[0].message.content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentReasoning)


def check_reasoning_history(model_name: str, include_history: bool):
    task = Task(
        dataset=[Sample(input="Please say hello, world")],
        solver=[
            generate(),
            user_message("Great!, now say 'goodbye, world'"),
            generate(),
        ],
    )

    log = eval(
        task,
        model=model_name,
        reasoning_history=include_history,
        reasoning_effort="low",
    )[0]
    assert log.samples
    sample = resolve_sample_attachments(log.samples[0])
    model_event = [event for event in sample.events if event.event == "model"][1]
    assistant_message = model_event.input[1]
    if include_history:
        assert "<think>" in assistant_message.text
    else:
        assert "<think>" not in assistant_message.text


@pytest.mark.asyncio
@skip_if_no_together
async def test_reasoning_content_together():
    await check_reasoning_content("together/deepseek-ai/DeepSeek-R1")


@pytest.mark.asyncio
@skip_if_no_groq
async def test_reasoning_content_groq():
    await check_reasoning_content("groq/deepseek-r1-distill-llama-70b")


@skip_if_no_google
def test_reasoning_content_google():
    log = eval(
        Task(dataset=[Sample(input="Solve 3*x^3-5*x=1")]),
        model="google/gemini-2.0-flash-thinking-exp",
    )[0]
    assert log.samples
    content = log.samples[0].output.message.content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentReasoning)


@pytest.mark.slow
@skip_if_no_together
def test_reasoning_history_together():
    check_reasoning_history("together/deepseek-ai/DeepSeek-R1", True)
    check_reasoning_history("together/deepseek-ai/DeepSeek-R1", False)
