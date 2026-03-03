from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._openai_responses import (
    MESSAGE_ID,
    MESSAGE_PHASE,
    _openai_input_items_from_chat_message_assistant,
)
from inspect_ai.model._providers.openai_compatible import ModelInfo
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
    """Test that multiple consecutive ContentReasoning blocks are all preserved."""

    class O1EarlyModelInfo(ModelInfo):
        def is_o1_early(self):
            return True

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

    # test that when using o-series we still collapse
    items = _openai_input_items_from_chat_message_assistant(message, O1EarlyModelInfo())
    reasoning_items = [item for item in items if item.get("type") == "reasoning"]
    assert len(reasoning_items) == 1
    assert reasoning_items[0]["id"] == "r3"

    # test that when not using o-series we don't collapse
    items = _openai_input_items_from_chat_message_assistant(message)
    reasoning_items = [item for item in items if item.get("type") == "reasoning"]
    assert len(reasoning_items) == 3
    ids = {item["id"] for item in reasoning_items}
    assert ids == {"r1", "r2", "r3"}


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
    """Test that all ContentReasoning blocks are preserved regardless of position."""
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

    assert len(reasoning_items) == 5
    ids = {item["id"] for item in reasoning_items}
    assert ids == {"r1", "r2", "r3", "r4", "r5"}


def test_fix_function_tool_parameters_string_to_dict():
    """Test that string parameters in FunctionTool are parsed to dicts."""
    from openai.types.responses import FunctionTool, Response

    from inspect_ai.model._providers.openai_responses import (
        _fix_function_tool_parameters,
    )

    tool = FunctionTool.model_construct(
        name="test_tool",
        type="function",
        parameters='{"type":"object","properties":{}}',
        strict=False,
    )
    response = Response.model_construct(
        id="test",
        created_at=0.0,
        model="test",
        object="response",
        output=[],
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[tool],
    )

    _fix_function_tool_parameters(response)

    dumped = response.model_dump()
    assert dumped["tools"][0]["parameters"] == {"type": "object", "properties": {}}


def test_chat_messages_from_compact_response():
    """Test that chat_messages_from_compact_response correctly converts compaction response."""
    from openai.types.responses import CompactedResponse, ResponseCompactionItem
    from openai.types.responses.response_usage import (
        InputTokensDetails,
        OutputTokensDetails,
        ResponseUsage,
    )

    from inspect_ai._util.content import ContentData
    from inspect_ai.model._chat_message import ChatMessageUser
    from inspect_ai.model._openai_responses import chat_messages_from_compact_response

    # Create a mock CompactedResponse with a ResponseCompactionItem
    compaction_item = ResponseCompactionItem(
        id="comp_123",
        encrypted_content="encrypted_data_here",
        type="compaction",
    )

    response = CompactedResponse(
        id="resp_abc",
        created_at=1234567890,
        object="response.compaction",
        output=[compaction_item],
        usage=ResponseUsage(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        ),
    )

    result = chat_messages_from_compact_response(response)

    # Verify the result is a list with a single ChatMessageUser
    assert len(result) == 1
    assert isinstance(result[0], ChatMessageUser)

    # Verify the content has the compaction metadata
    content = result[0].content
    assert isinstance(content, list)
    assert len(content) == 1
    assert isinstance(content[0], ContentData)

    metadata = content[0].data
    assert metadata["compaction_metadata"]["type"] == "openai_compact"
    assert metadata["compaction_metadata"]["id"] == "comp_123"
    assert metadata["compaction_metadata"]["encrypted_content"] == "encrypted_data_here"


def test_chat_messages_from_compact_response_no_compaction_item():
    """Test that chat_messages_from_compact_response raises on missing compaction item."""
    import pytest
    from openai.types.responses import CompactedResponse
    from openai.types.responses.response_usage import (
        InputTokensDetails,
        OutputTokensDetails,
        ResponseUsage,
    )

    from inspect_ai.model._openai_responses import chat_messages_from_compact_response

    # Create a CompactedResponse without a ResponseCompactionItem
    response = CompactedResponse(
        id="resp_abc",
        created_at=1234567890,
        object="response.compaction",
        output=[],  # No compaction item
        usage=ResponseUsage(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        ),
    )

    with pytest.raises(ValueError, match="No ResponseCompactionItem found"):
        chat_messages_from_compact_response(response)


def test_model_usage_from_compact_response():
    """Test that model_usage_from_compact_response correctly extracts usage."""
    from openai.types.responses import CompactedResponse, ResponseCompactionItem
    from openai.types.responses.response_usage import (
        InputTokensDetails,
        OutputTokensDetails,
        ResponseUsage,
    )

    from inspect_ai.model._openai_responses import model_usage_from_compact_response

    compaction_item = ResponseCompactionItem(
        id="comp_123",
        encrypted_content="encrypted_data_here",
        type="compaction",
    )

    response = CompactedResponse(
        id="resp_abc",
        created_at=1234567890,
        object="response.compaction",
        output=[compaction_item],
        usage=ResponseUsage(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        ),
    )

    usage = model_usage_from_compact_response(response)

    assert usage is not None
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.total_tokens == 150


def test_extract_compaction_from_content_data():
    """Test that compaction metadata is correctly extracted from ContentData."""
    from inspect_ai._util.content import ContentData, ContentText
    from inspect_ai.model._openai_responses import _extract_compaction_from_content_data

    # Test with compaction metadata
    content_with_compaction = [
        ContentText(text="Some text"),
        ContentData(
            data={
                "compaction_metadata": {
                    "type": "openai_compact",
                    "id": "comp_456",
                    "encrypted_content": "encrypted_stuff",
                }
            }
        ),
    ]

    result = _extract_compaction_from_content_data(content_with_compaction)
    assert result is not None
    assert result["type"] == "compaction"
    assert result["id"] == "comp_456"
    assert result["encrypted_content"] == "encrypted_stuff"


def test_extract_compaction_from_content_data_no_compaction():
    """Test that None is returned when no compaction metadata present."""
    from inspect_ai._util.content import ContentText
    from inspect_ai.model._openai_responses import _extract_compaction_from_content_data

    # Test without compaction metadata
    content_without_compaction = [
        ContentText(text="Some text"),
    ]

    result = _extract_compaction_from_content_data(content_without_compaction)
    assert result is None

    # Test with string content
    result = _extract_compaction_from_content_data("Just a string")
    assert result is None


def test_chat_messages_from_compact_response_mixed_items():
    """Test that chat_messages_from_compact_response handles mixed items correctly."""
    from openai.types.responses import (
        CompactedResponse,
        ResponseCompactionItem,
        ResponseOutputMessage,
        ResponseOutputText,
    )
    from openai.types.responses.response_usage import (
        InputTokensDetails,
        OutputTokensDetails,
        ResponseUsage,
    )

    from inspect_ai._util.content import ContentData
    from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
    from inspect_ai.model._openai_responses import chat_messages_from_compact_response

    # Create a CompactedResponse with compaction item followed by an output message
    compaction_item = ResponseCompactionItem(
        id="comp_123",
        encrypted_content="encrypted_data_here",
        type="compaction",
    )

    output_message = ResponseOutputMessage(
        id="msg_456",
        type="message",
        role="assistant",
        status="completed",
        content=[
            ResponseOutputText(
                type="output_text", text="Recent response", annotations=[]
            )
        ],
    )

    response = CompactedResponse(
        id="resp_abc",
        created_at=1234567890,
        object="response.compaction",
        output=[compaction_item, output_message],
        usage=ResponseUsage(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        ),
    )

    result = chat_messages_from_compact_response(response, model="codex-mini")

    # Verify we get two messages in order: compaction user message, then assistant message
    assert len(result) == 2

    # First message should be the compaction metadata
    assert isinstance(result[0], ChatMessageUser)
    content = result[0].content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentData)
    assert content[0].data["compaction_metadata"]["id"] == "comp_123"

    # Second message should be the assistant message with model and source set
    assert isinstance(result[1], ChatMessageAssistant)
    assert result[1].text == "Recent response"
    assert result[1].model == "codex-mini"
    assert result[1].source == "generate"


def test_chat_messages_from_compact_response_developer_and_user_messages():
    """Test that developer messages are stripped and user messages are preserved."""
    from openai.types.responses import (
        CompactedResponse,
        ResponseCompactionItem,
        ResponseOutputMessage,
        ResponseOutputText,
    )
    from openai.types.responses.response_usage import (
        InputTokensDetails,
        OutputTokensDetails,
        ResponseUsage,
    )

    from inspect_ai._util.content import ContentData, ContentText
    from inspect_ai.model._chat_message import ChatMessageUser
    from inspect_ai.model._openai_responses import chat_messages_from_compact_response

    # Create a compact response matching real API output:
    # developer message, user messages, then compaction item.
    # Use model_construct to bypass Pydantic validation since the SDK types
    # restrict role to Literal["assistant"], but the real API returns
    # developer/user roles in compact responses.
    developer_msg = ResponseOutputMessage.model_construct(
        id="msg_dev",
        type="message",
        role="developer",
        status="completed",
        content=[
            ResponseOutputText(
                type="output_text", text="You are a helpful assistant.", annotations=[]
            )
        ],
    )

    user_msg1 = ResponseOutputMessage.model_construct(
        id="msg_user1",
        type="message",
        role="user",
        status="completed",
        content=[
            ResponseOutputText(type="output_text", text="Hello there", annotations=[])
        ],
    )

    user_msg2 = ResponseOutputMessage.model_construct(
        id="msg_user2",
        type="message",
        role="user",
        status="completed",
        content=[
            ResponseOutputText(type="output_text", text="How are you?", annotations=[])
        ],
    )

    compaction_item = ResponseCompactionItem(
        id="comp_123",
        encrypted_content="encrypted_data_here",
        type="compaction",
    )

    response = CompactedResponse(
        id="resp_abc",
        created_at=1234567890,
        object="response.compaction",
        output=[developer_msg, user_msg1, user_msg2, compaction_item],
        usage=ResponseUsage(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        ),
    )

    result = chat_messages_from_compact_response(response)

    # Developer message should be stripped, user messages preserved,
    # compaction item becomes ContentData
    assert len(result) == 3

    # First two should be user messages
    assert isinstance(result[0], ChatMessageUser)
    assert isinstance(result[0].content, list)
    assert isinstance(result[0].content[0], ContentText)
    assert result[0].content[0].text == "Hello there"

    assert isinstance(result[1], ChatMessageUser)
    assert isinstance(result[1].content, list)
    assert isinstance(result[1].content[0], ContentText)
    assert result[1].content[0].text == "How are you?"

    # Last should be compaction metadata
    assert isinstance(result[2], ChatMessageUser)
    assert isinstance(result[2].content, list)
    assert isinstance(result[2].content[0], ContentData)
    assert result[2].content[0].data["compaction_metadata"]["id"] == "comp_123"


def test_chat_messages_from_compact_response_mixed_roles():
    """Test compact response with developer, user, compaction, and assistant items."""
    from openai.types.responses import (
        CompactedResponse,
        ResponseCompactionItem,
        ResponseOutputMessage,
        ResponseOutputText,
    )
    from openai.types.responses.response_usage import (
        InputTokensDetails,
        OutputTokensDetails,
        ResponseUsage,
    )

    from inspect_ai._util.content import ContentData, ContentText
    from inspect_ai.model._chat_message import (
        ChatMessageAssistant,
        ChatMessageUser,
    )
    from inspect_ai.model._openai_responses import chat_messages_from_compact_response

    # Use model_construct for developer/user roles (see note in previous test)
    developer_msg = ResponseOutputMessage.model_construct(
        id="msg_dev",
        type="message",
        role="developer",
        status="completed",
        content=[
            ResponseOutputText(type="output_text", text="System prompt", annotations=[])
        ],
    )

    user_msg = ResponseOutputMessage.model_construct(
        id="msg_user",
        type="message",
        role="user",
        status="completed",
        content=[
            ResponseOutputText(type="output_text", text="User question", annotations=[])
        ],
    )

    compaction_item = ResponseCompactionItem(
        id="comp_456",
        encrypted_content="encrypted_stuff",
        type="compaction",
    )

    assistant_msg = ResponseOutputMessage(
        id="msg_asst",
        type="message",
        role="assistant",
        status="completed",
        content=[
            ResponseOutputText(
                type="output_text", text="Assistant reply", annotations=[]
            )
        ],
    )

    response = CompactedResponse(
        id="resp_xyz",
        created_at=1234567890,
        object="response.compaction",
        output=[developer_msg, user_msg, compaction_item, assistant_msg],
        usage=ResponseUsage(
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        ),
    )

    result = chat_messages_from_compact_response(response, model="gpt-4o")

    # developer stripped, user -> ChatMessageUser, compaction -> ContentData,
    # assistant -> ChatMessageAssistant
    assert len(result) == 3

    # User message
    assert isinstance(result[0], ChatMessageUser)
    assert isinstance(result[0].content, list)
    assert isinstance(result[0].content[0], ContentText)
    assert result[0].content[0].text == "User question"

    # Compaction metadata
    assert isinstance(result[1], ChatMessageUser)
    assert isinstance(result[1].content, list)
    assert isinstance(result[1].content[0], ContentData)
    assert result[1].content[0].data["compaction_metadata"]["id"] == "comp_456"

    # Assistant message
    assert isinstance(result[2], ChatMessageAssistant)
    assert result[2].text == "Assistant reply"
    assert result[2].model == "gpt-4o"
    assert result[2].source == "generate"


def test_phase_round_trip():
    """Test that the phase field from Codex models is preserved through round-trip."""
    # Create a message with phase stored in ContentText.internal
    message = ChatMessageAssistant(
        content=[
            ContentText(
                text="Working on it...",
                internal={MESSAGE_ID: "msg_1", MESSAGE_PHASE: "commentary"},
            ),
            ContentText(
                text="Here is the answer.",
                internal={MESSAGE_ID: "msg_2", MESSAGE_PHASE: "final_answer"},
            ),
        ],
        model="test",
        source="generate",
    )

    items = _openai_input_items_from_chat_message_assistant(message)

    # Should produce two message items (different message IDs)
    message_items = [item for item in items if item.get("type") == "message"]
    assert len(message_items) == 2

    # First message should have phase="commentary"
    assert message_items[0]["phase"] == "commentary"
    assert message_items[0]["content"][0]["text"] == "Working on it..."

    # Second message should have phase="final_answer"
    assert message_items[1]["phase"] == "final_answer"
    assert message_items[1]["content"][0]["text"] == "Here is the answer."


def test_phase_round_trip_no_phase():
    """Test that messages without phase don't get a phase field."""
    message = ChatMessageAssistant(
        content=[
            ContentText(
                text="Hello",
                internal={MESSAGE_ID: "msg_1"},
            ),
        ],
        model="test",
        source="generate",
    )

    items = _openai_input_items_from_chat_message_assistant(message)
    message_items = [item for item in items if item.get("type") == "message"]
    assert len(message_items) == 1
    assert "phase" not in message_items[0]


def test_phase_round_trip_mixed():
    """Test messages where some have phase and some don't."""
    message = ChatMessageAssistant(
        content=[
            ContentText(
                text="No phase here",
                internal={MESSAGE_ID: "msg_1"},
            ),
            ContentText(
                text="Has phase",
                internal={MESSAGE_ID: "msg_2", MESSAGE_PHASE: "commentary"},
            ),
        ],
        model="test",
        source="generate",
    )

    items = _openai_input_items_from_chat_message_assistant(message)
    message_items = [item for item in items if item.get("type") == "message"]
    assert len(message_items) == 2

    # First message: no phase
    assert "phase" not in message_items[0]

    # Second message: has phase
    assert message_items[1]["phase"] == "commentary"
