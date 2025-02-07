import pytest
from test_helpers.utils import skip_if_no_groq, skip_if_no_together

from inspect_ai import Task, eval
from inspect_ai.dataset._dataset import Sample
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
    assert output.choices[0].message.reasoning is not None


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
    model_event = [event for event in log.samples[0].events if event.event == "model"][
        1
    ]
    assistant_message = model_event.input[1]
    if assistant_message.text.startswith("attachment://"):
        attachment_id = assistant_message.text.removeprefix("attachment://")
        message_content = log.samples[0].attachments[attachment_id]
    else:
        message_content = assistant_message.text
    if include_history:
        assert "<think>" in message_content
    else:
        assert "<think>" not in message_content


@pytest.mark.asyncio
@skip_if_no_together
async def test_reasoning_content_together():
    await check_reasoning_content("together/deepseek-ai/DeepSeek-R1")


@pytest.mark.asyncio
@skip_if_no_groq
async def test_reasoning_content_groq():
    await check_reasoning_content("groq/deepseek-r1-distill-llama-70b")


@pytest.mark.slow
@skip_if_no_together
def test_reasoning_history_together():
    check_reasoning_history("together/deepseek-ai/DeepSeek-R1", True)
    check_reasoning_history("together/deepseek-ai/DeepSeek-R1", False)
