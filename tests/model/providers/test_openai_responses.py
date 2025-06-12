from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._openai_responses import (
    _openai_input_items_from_chat_message_assistant,
)
from inspect_ai.solver import generate, user_message


def get_responses_model(config: GenerateConfig = GenerateConfig()):
    return get_model(
        "openai/gpt-4o-mini",
        config=config,
        responses_api=True,
    )


@skip_if_no_openai
def test_openai_responses_api():
    log = eval(
        Task(dataset=[Sample(input="This is a test string. What are you?")]),
        model=get_responses_model(
            config=GenerateConfig(
                max_tokens=50,
                temperature=0.5,
                top_p=1.0,
            )
        ),
    )[0]
    assert log.status == "success"


@skip_if_no_openai
def test_openai_responses_assistant_messages():
    log = eval(
        Task(dataset=[Sample(input="Please tell me your favorite color")]),
        solver=[
            generate(),
            user_message("Terrific! Now share your favorite shape."),
            generate(),
            user_message("Delightful! Now share your favorite texture."),
        ],
        model=get_responses_model(),
    )[0]
    assert log.status == "success"


@skip_if_no_openai
def test_openai_responses_o1_pro():
    log = eval(
        Task(dataset=[Sample(input="Please tell me your favorite color")]),
        model="openai/o1-pro",
    )[0]
    assert log.status == "success"


@skip_if_no_openai
def test_openai_responses_no_store():
    log = eval(Task(), model="openai/o4-mini", model_args=dict(responses_store=False))[
        0
    ]
    assert log.status == "success"


def test_multiple_consecutive_reasoning_blocks_filtering():
    """Test that multiple consecutive ContentReasoning blocks are filtered to keep only the last one."""
    message = ChatMessageAssistant(
        content=[
            ContentText(text="First text"),
            ContentReasoning(reasoning="First reasoning", signature="r1"),
            ContentReasoning(reasoning="Second reasoning", signature="r2"),
            ContentReasoning(reasoning="Third reasoning", signature="r3"),
            ContentText(text="Second text"),
        ],
        model="test",
        source="generate",
    )

    items = _openai_input_items_from_chat_message_assistant(message)
    reasoning_items = [item for item in items if item.get("type") == "reasoning"]

    assert len(reasoning_items) == 1
    assert reasoning_items[0]["id"] == "r3"


def test_non_consecutive_reasoning_blocks_filtering():
    """Test that non-consecutive ContentReasoning blocks are both kept."""
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="First reasoning", signature="r1"),
            ContentText(text="Middle text"),
            ContentReasoning(reasoning="Second reasoning", signature="r2"),
        ],
        model="test",
        source="generate",
    )

    items = _openai_input_items_from_chat_message_assistant(message)
    reasoning_items = [item for item in items if item.get("type") == "reasoning"]

    assert len(reasoning_items) == 2
    ids = {item["id"] for item in reasoning_items}
    assert ids == {"r1", "r2"}


def test_mixed_reasoning_blocks_filtering():
    """Test that mixed consecutive and non-consecutive ContentReasoning blocks are properly filtered."""
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="First reasoning", signature="r1"),
            ContentText(text="Text 1"),
            ContentReasoning(reasoning="Second reasoning", signature="r2"),
            ContentReasoning(reasoning="Third reasoning", signature="r3"),
            ContentReasoning(reasoning="Fourth reasoning", signature="r4"),
            ContentText(text="Text 2"),
            ContentReasoning(reasoning="Fifth reasoning", signature="r5"),
        ],
        model="test",
        source="generate",
    )

    items = _openai_input_items_from_chat_message_assistant(message)
    reasoning_items = [item for item in items if item.get("type") == "reasoning"]

    assert len(reasoning_items) == 3
    ids = {item["id"] for item in reasoning_items}
    assert ids == {"r1", "r4", "r5"}
