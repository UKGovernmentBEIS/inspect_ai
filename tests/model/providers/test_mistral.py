import pytest
from test_helpers.utils import skip_if_no_mistral, skip_if_no_mistral_package

from inspect_ai._util.content import ContentImage
from inspect_ai._util.images import UnresolvedMediaError
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.tool import (
    ToolInfo,
    ToolParam,
    ToolParams,
)


@pytest.fixture
def tiktok_tool_with_description_param():
    """Fixture that provides a tool with a parameter named 'description'.

    This tool is specifically designed to test handling of parameters named 'description',
    which previously caused issues with the Mistral API.
    """
    return ToolInfo(
        name="upload_tiktok_video",
        description="Upload a video to TikTok with description and tags.",
        parameters=ToolParams(
            type="object",
            properties={
                "video_path": ToolParam(
                    type="string",
                    description="The file path of the video to be uploaded",
                ),
                "description": ToolParam(
                    type="string",
                    description="The description for the TikTok video",
                ),
            },
            required=["video_path", "description"],
        ),
    )


@skip_if_no_mistral_package
def test_mistral_tool_schema_formatting(tiktok_tool_with_description_param):
    """Test that the tool schema is correctly formatted for the Mistral API.

    This test verifies that our tool schema conversion correctly includes the outer schema
    structure with type, properties, and required fields that Mistral expects.
    """
    from inspect_ai.model._providers.mistral import mistral_chat_tools

    # Convert the tool to Mistral format
    mistral_tools = mistral_chat_tools([tiktok_tool_with_description_param])

    # Verify the structure
    assert len(mistral_tools) == 1
    mistral_tool = mistral_tools[0]

    # Check that the tool has the correct type
    assert mistral_tool.type == "function"

    # Check that the function has the correct name and description
    assert mistral_tool.function.name == "upload_tiktok_video"
    assert (
        mistral_tool.function.description
        == "Upload a video to TikTok with description and tags."
    )

    # Check that the parameters have the correct structure
    params = mistral_tool.function.parameters
    assert params["type"] == "object"
    assert "properties" in params
    assert "required" in params
    assert params["required"] == ["video_path", "description"]

    # Check that the properties have the correct structure
    properties = params["properties"]
    assert "video_path" in properties
    assert "description" in properties
    assert properties["video_path"]["type"] == "string"
    assert properties["description"]["type"] == "string"


@pytest.mark.anyio
@skip_if_no_mistral
@skip_if_no_mistral_package
async def test_mistral_with_description_parameter(tiktok_tool_with_description_param):
    """Test that the Mistral API correctly accepts a tool with a parameter named 'description'.

    This test verifies that our fix for the tool schema formatting works correctly
    when calling the actual Mistral API.
    """
    model = get_model(
        "mistral/mistral-small-latest",
        config=GenerateConfig(
            temperature=0.0,
        ),
    )

    # Create a simple prompt
    messages = [
        ChatMessageUser(content="Hello, can you help me upload a video to TikTok?")
    ]

    # Use the tool with a parameter named 'description'
    tools = [tiktok_tool_with_description_param]

    try:
        # This should no longer raise an error with our fix
        result = await model.generate(messages, tools=tools)
        # If we get here, the test passed
        assert result is not None, "Expected a result from the model"
    except Exception as e:
        pytest.fail(f"Test failed with exception: {e}")


@skip_if_no_mistral_package
def test_completion_content_chunks_image_url_string():
    """Test that ImageURLChunk with string URL converts to ContentImage."""
    from mistralai.client.models import ImageURLChunk

    from inspect_ai.model._providers.mistral import completion_content_chunks

    chunk = ImageURLChunk(image_url="data:image/png;base64,abc123")
    result = completion_content_chunks(chunk)
    assert len(result) == 1
    assert isinstance(result[0], ContentImage)
    assert result[0].image == "data:image/png;base64,abc123"


@skip_if_no_mistral_package
def test_completion_content_chunks_image_url_object():
    """Test that ImageURLChunk with ImageURL object converts to ContentImage with detail."""
    from mistralai.client.models import ImageURL, ImageURLChunk

    from inspect_ai.model._providers.mistral import completion_content_chunks

    chunk = ImageURLChunk(
        image_url=ImageURL(url="https://example.com/img.png", detail="high")
    )
    result = completion_content_chunks(chunk)
    assert len(result) == 1
    assert isinstance(result[0], ContentImage)
    assert result[0].image == "https://example.com/img.png"
    assert result[0].detail == "high"


@skip_if_no_mistral_package
async def test_mistral_output_url_is_not_fetched_on_replay():
    from mistralai.client.models import ImageURL, ImageURLChunk

    from inspect_ai.model._providers.mistral import (
        completion_content_chunks,
        mistral_content_chunk,
    )

    chunk = ImageURLChunk(
        image_url=ImageURL(url="https://example.com/img.png", detail="high")
    )
    content = completion_content_chunks(chunk)[0]

    with pytest.raises(UnresolvedMediaError, match="materialized"):
        await mistral_content_chunk(content)


@skip_if_no_mistral_package
async def test_mistral_chat_forwards_config_extra_headers() -> None:
    """config.extra_headers must reach the chat completions request.

    The conversation-api path already merges them; this covers the chat path.
    """
    from unittest import mock
    from unittest.mock import AsyncMock, MagicMock

    import httpx

    from inspect_ai.model._providers.mistral import MistralAPI
    from inspect_ai.model._providers.util.hooks import HttpxHooks

    api = MistralAPI(
        model_name="mistral/mistral-small-latest",
        api_key="test-key",
        conversation_api=False,
    )

    captured: dict[str, object] = {}

    async def _capture(**kwargs: object) -> object:
        captured.update(kwargs)
        raise RuntimeError("stop after capture")

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.sdk_configuration.async_client = httpx.AsyncClient()
    client.chat.complete_async = AsyncMock(side_effect=_capture)

    with mock.patch("inspect_ai.model._providers.mistral.Mistral", return_value=client):
        with pytest.raises(RuntimeError, match="stop after capture"):
            await api.generate(
                input=[ChatMessageUser(content="hi")],
                tools=[],
                tool_choice="none",
                config=GenerateConfig(
                    extra_headers={"x-custom-header": "custom-value"}
                ),
            )

    http_headers = captured["http_headers"]
    assert isinstance(http_headers, dict)
    assert http_headers["x-custom-header"] == "custom-value"
    assert HttpxHooks.REQUEST_ID_HEADER in http_headers
