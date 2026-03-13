import base64

import pytest
from test_helpers.utils import flaky_retry, skip_if_no_google, skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.dataset import Sample
from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig, ImageOutput
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import model_graded_fact


def test_scorer_receives_image_output():
    """End-to-end: model_graded_fact scorer receives ContentImage from model output."""
    test_image = ContentImage(image="data:image/png;base64,iVBORw0KGgo=")
    output = ModelOutput.from_content(
        "mockllm/model",
        content=[ContentText(text="Here is the result"), test_image],
    )
    model = get_model("mockllm/model", custom_outputs=[output])

    task = Task(
        dataset=[Sample(input="Generate an image", target="result")],
        scorer=model_graded_fact(model="mockllm/model"),
    )
    log = eval(task, model=model)[0]

    # Verify the image was presented to the grader model
    sample = resolve_sample_attachments(log.samples[0], "full")
    model_event = next(
        event for event in reversed(sample.events) if event.event == "model"
    )
    content = model_event.input[0].content
    assert isinstance(content, list)
    assert any(isinstance(c, ContentImage) for c in content)


async def check_openai_responses_image_generation(model_name: str):
    model = get_model(model_name)
    output = await model.generate(
        input=[ChatMessageUser(content="Generate a simple image of a blue square")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(modalities=["image"]),
    )
    content = output.choices[0].message.content
    assert isinstance(content, list)
    images = [c for c in content if isinstance(c, ContentImage)]
    assert len(images) >= 1
    assert images[0].image.startswith("data:image/png;base64,")
    _, b64data = images[0].image.split(",", 1)
    raw = base64.b64decode(b64data)
    assert raw[:4] == b"\x89PNG"


@pytest.mark.slow
@skip_if_no_openai
async def test_openai_responses_image_generation_gpt4():
    await check_openai_responses_image_generation("openai/gpt-4o")


@pytest.mark.slow
@skip_if_no_openai
async def test_openai_responses_image_generation_gpt5():
    await check_openai_responses_image_generation("openai/gpt-5.4")


@pytest.mark.slow
@skip_if_no_openai
async def test_openai_responses_image_generation_gpt5_with_options():
    """Test image generation with provider-specific ImageOutput options."""
    model = get_model("openai/gpt-5.4")
    output = await model.generate(
        input=[ChatMessageUser(content="Generate a simple image of a blue square")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(
            modalities=[
                ImageOutput(
                    options={
                        "openai": {
                            "quality": "low",
                            "size": "1024x1024",
                            "output_format": "png",
                        }
                    }
                )
            ]
        ),
    )
    content = output.choices[0].message.content
    assert isinstance(content, list)
    images = [c for c in content if isinstance(c, ContentImage)]
    assert len(images) >= 1
    assert images[0].image.startswith("data:image/png;base64,")
    _, b64data = images[0].image.split(",", 1)
    raw = base64.b64decode(b64data)
    assert raw[:4] == b"\x89PNG"


@pytest.mark.slow
@skip_if_no_google
async def test_google_image_generation():
    model = get_model("google/gemini-3.1-flash-image-preview")
    output = await model.generate(
        input=[
            ChatMessageUser(
                content="Generate a simple image of a red circle on white background"
            )
        ],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(modalities=["image"]),
    )
    content = output.choices[0].message.content
    assert isinstance(content, list)
    images = [c for c in content if isinstance(c, ContentImage)]
    assert len(images) >= 1
    assert images[0].image.startswith("data:image/")
    _, b64data = images[0].image.split(",", 1)
    raw = base64.b64decode(b64data)
    assert raw[:4] == b"\x89PNG" or raw[:3] == b"\xff\xd8\xff"


@pytest.mark.slow
@skip_if_no_openai
async def test_openai_responses_image_replay():
    """Test that a generated image can be replayed in a follow-up turn."""
    model = get_model("openai/gpt-5.4")
    # Turn 1: generate image — don't mention the color so turn 2 must see the image
    output1 = await model.generate(
        input=[
            ChatMessageUser(
                content="Generate a simple image of a square filled with a color of your choice"
            )
        ],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(modalities=["image"]),
    )
    content1 = output1.choices[0].message.content
    assert isinstance(content1, list)
    images = [c for c in content1 if isinstance(c, ContentImage)]
    assert len(images) >= 1

    # Turn 2: ask about the generated image (model must see the image to answer)
    output2 = await model.generate(
        input=[
            ChatMessageUser(
                content="Generate a simple image of a square filled with a color of your choice"
            ),
            ChatMessageAssistant(
                content=content1, model=output1.model, source="generate"
            ),
            ChatMessageUser(
                content="What color is the square in the image you generated? Reply with just the color name."
            ),
        ],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
    )
    assert output2.choices[0].message.text


@pytest.mark.slow
@skip_if_no_google
@flaky_retry(max_retries=3)
async def test_google_image_replay():
    """Test that a generated image can be replayed in a follow-up turn."""
    model = get_model("google/gemini-3.1-flash-image-preview")
    # Turn 1: generate image — don't mention the color so turn 2 must see the image
    output1 = await model.generate(
        input=[
            ChatMessageUser(
                content="Generate a simple image of a circle filled with a color of your choice"
            )
        ],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(modalities=["image"]),
    )
    content1 = output1.choices[0].message.content
    assert isinstance(content1, list)
    images = [c for c in content1 if isinstance(c, ContentImage)]
    assert len(images) >= 1

    # Turn 2: ask about the generated image (model must see the image to answer)
    output2 = await model.generate(
        input=[
            ChatMessageUser(
                content="Generate a simple image of a circle filled with a color of your choice"
            ),
            ChatMessageAssistant(
                content=content1, model=output1.model, source="generate"
            ),
            ChatMessageUser(
                content="What color is the circle in the image you generated? Reply with just the color name."
            ),
        ],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
    )
    assert output2.choices[0].message.text
