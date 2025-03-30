import pytest
from test_helpers.utils import skip_if_no_mistral, skip_if_no_mistral_package

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
