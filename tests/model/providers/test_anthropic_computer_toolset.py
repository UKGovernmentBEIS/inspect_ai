"""Anthropic computer toolset (`computer_toolset_20260801`) support.

Covers tool declaration mode selection per model/platform/model arg, inbound
member translation, outbound `tool_use`/`tool_result` replay (`toolset_name`),
and beta header handling. No live API calls.
"""

from typing import Any, cast
from unittest.mock import patch

import pytest
from anthropic.types import MessageParam, ToolUseBlock
from test_helpers.utils import setenv_if_unset

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.anthropic import (
    COMPUTER_TOOLSET_TYPE,
    AnthropicAPI,
    ToolParamDef,
    assistant_message_block_params,
    content_and_tool_calls_from_assistant_content_blocks,
    init_sample_anthropic_assistant_internal,
    is_computer_toolset,
    message_param,
)
from inspect_ai.tool import ToolCall, ToolInfo
from inspect_ai.tool._tool_call import ToolCallError
from inspect_ai.tool._tool_params import ToolParam, ToolParams
from inspect_ai.tool._tools._computer._computer import _COMPUTER_TOOL_PARAMETERS

LEGACY = "computer_20251124"
TOOLSET = COMPUTER_TOOLSET_TYPE
NOT_EXECUTED = "Not executed: an earlier computer action in this turn failed."
PNG_DATA_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def computer_tool_info() -> ToolInfo:
    """A ToolInfo that satisfies is_computer_tool_info() (inspect's computer())."""
    return ToolInfo(
        name="computer",
        description="computer",
        parameters=ToolParams(
            properties={k: ToolParam(type="string") for k in _COMPUTER_TOOL_PARAMETERS}
        ),
    )


def anthropic_api(model_name: str, **model_args: Any) -> AnthropicAPI:
    setenv_if_unset("AWS_REGION", "us-east-1")
    setenv_if_unset("AWS_ACCESS_KEY_ID", "fake")
    setenv_if_unset("AWS_SECRET_ACCESS_KEY", "fake")
    setenv_if_unset("ANTHROPIC_VERTEX_PROJECT_ID", "fake")
    setenv_if_unset("ANTHROPIC_VERTEX_REGION", "us-east5")
    setenv_if_unset("AZUREAI_ANTHROPIC_BASE_URL", "https://fake.services.ai.azure.com")
    return AnthropicAPI(model_name=model_name, api_key="test-key", **model_args)


def computer_param(model_name: str, **model_args: Any) -> ToolParamDef:
    param = anthropic_api(model_name, **model_args).computer_use_tool_param(
        computer_tool_info()
    )
    assert param is not None
    return param


def first_block(param: MessageParam) -> dict[str, Any]:
    """The first content block of a message param, as a plain dict."""
    return cast(dict[str, Any], list(param["content"])[0])


# ---------------------------------------------------------------------------
# Tool declaration: mode selection by model / platform / model arg
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name,expected_type",
    [
        # Opus 5.5: the legacy tool is rejected on the Claude API and Vertex;
        # Bedrock and Foundry offer only the legacy tool (prior behavior kept)
        ("claude-opus-5-5", TOOLSET),
        ("vertex/claude-opus-5-5", TOOLSET),
        ("azure/claude-opus-5-5", LEGACY),
        ("bedrock/anthropic.claude-opus-5-5", LEGACY),
        # Fable/Mythos 5.x default to the toolset where it is offered
        ("claude-fable-5", TOOLSET),
        ("claude-fable-5-1", TOOLSET),
        ("claude-mythos-5", TOOLSET),
        ("claude-mythos-5-1", TOOLSET),
        ("vertex/claude-fable-5-1", TOOLSET),
        # forward-compat: an unknown Claude 5 codename gets the toolset
        ("claude-saga-5", TOOLSET),
        # everything else keeps the legacy tool (prior behavior)
        ("claude-opus-5", LEGACY),
        ("claude-sonnet-5", LEGACY),
        ("claude-opus-4-8", LEGACY),
        ("claude-opus-4-6", LEGACY),
        ("claude-sonnet-4-6", LEGACY),
        ("vertex/claude-opus-5", LEGACY),
        ("bedrock/anthropic.claude-opus-5", LEGACY),
        ("claude-sonnet-4-5", "computer_20250124"),
    ],
)
def test_computer_use_mode_by_model_and_platform(
    model_name: str, expected_type: str
) -> None:
    assert computer_param(model_name)["type"] == expected_type


@pytest.mark.parametrize(
    "model_name",
    [
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-opus-4-8",
        "vertex/claude-sonnet-5",
    ],
)
def test_computer_toolset_model_arg_forces_toolset(model_name: str) -> None:
    assert computer_param(model_name, computer_toolset=True)["type"] == TOOLSET


@pytest.mark.parametrize(
    "model_name",
    [
        "bedrock/anthropic.claude-opus-5-5",
        "azure/claude-opus-5",
        "bedrock/anthropic.claude-sonnet-5",
    ],
)
def test_computer_toolset_model_arg_rejected_off_claude_api_and_vertex(
    model_name: str,
) -> None:
    """Bedrock and Foundry offer only the legacy tool, so forcing the toolset errors."""
    with pytest.raises(PrerequisiteError) as exc_info:
        computer_param(model_name, computer_toolset=True)
    message = str(exc_info.value.message)
    assert "only offered on the Claude API and Vertex" in message
    assert "computer_toolset=true" in message


@pytest.mark.parametrize(
    "model_name",
    [
        "bedrock/anthropic.claude-fable-5-1",
        "azure/claude-mythos-5",
        "bedrock/anthropic.claude-saga-5",
    ],
)
def test_fable_mythos_fall_back_to_legacy_off_claude_api_and_vertex(
    model_name: str,
) -> None:
    """Bedrock/Foundry offer only the legacy tool, which Fable/Mythos accept."""
    assert computer_param(model_name)["type"] == LEGACY


@pytest.mark.parametrize("model_name", ["claude-opus-4-6", "claude-sonnet-4-5"])
def test_computer_toolset_model_arg_rejected_on_unsupported_model(
    model_name: str,
) -> None:
    with pytest.raises(PrerequisiteError) as exc_info:
        computer_param(model_name, computer_toolset=True)
    message = str(exc_info.value.message)
    assert "computer_toolset_20260801" in message
    assert model_name in message


@pytest.mark.parametrize(
    "model_name,expected_type",
    [
        ("bedrock/anthropic.claude-opus-5-5", LEGACY),
        ("claude-opus-5", LEGACY),
        # Fable/Mythos accept the legacy tool (computer-use docs, earlier tool versions)
        ("claude-fable-5-1", LEGACY),
        ("vertex/claude-mythos-5", LEGACY),
    ],
)
def test_computer_toolset_false_keeps_legacy_where_supported(
    model_name: str, expected_type: str
) -> None:
    assert computer_param(model_name, computer_toolset=False)["type"] == expected_type


@pytest.mark.parametrize("model_name", ["claude-opus-5-5", "vertex/claude-opus-5-5"])
def test_computer_toolset_false_rejected_where_legacy_unsupported(
    model_name: str,
) -> None:
    with pytest.raises(PrerequisiteError) as exc_info:
        computer_param(model_name, computer_toolset=False)
    message = str(exc_info.value.message)
    assert "computer_20251124" in message
    assert "computer_toolset=false" in message


@pytest.mark.parametrize(
    "value,expected", [("true", True), ("False", False), ("auto", None), (None, None)]
)
def test_computer_toolset_model_arg_normalization(
    value: Any, expected: bool | None
) -> None:
    api = anthropic_api("claude-opus-5", computer_toolset=value)
    assert api.computer_toolset is expected


def test_computer_toolset_model_arg_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="computer_toolset"):
        anthropic_api("claude-opus-5", computer_toolset="yes please")


def test_toolset_param_has_no_name_or_display_fields() -> None:
    param = computer_param("claude-opus-5-5")
    assert param == {"type": TOOLSET}
    assert is_computer_toolset(param)


def test_legacy_param_unchanged() -> None:
    param = computer_param("claude-opus-5")
    assert param == {
        "type": LEGACY,
        "name": "computer",
        "display_width_px": 1366,
        "display_height_px": 768,
        "display_number": 1,
        "enable_zoom": True,
    }
    assert not is_computer_toolset(param)


# ---------------------------------------------------------------------------
# Inbound: toolset member tool_use -> computer tool call with `action`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member,member_input",
    [
        ("screenshot", {}),
        ("zoom", {"region": [100, 100, 500, 400]}),
        ("left_click", {"coordinate": [10, 20]}),
        ("left_click_drag", {"start_coordinate": [1, 2], "coordinate": [30, 40]}),
        (
            "scroll",
            {"coordinate": [5, 6], "scroll_direction": "down", "scroll_amount": 3},
        ),
        ("key", {"text": "Return", "repeat": 3}),
        ("hold_key", {"text": "shift", "duration": 2}),
        ("type", {"text": "hello"}),
        ("wait", {"duration": 1}),
        ("cursor_position", {}),
    ],
)
def test_inbound_member_translation(member: str, member_input: dict[str, Any]) -> None:
    init_sample_anthropic_assistant_internal()
    block = ToolUseBlock(
        type="tool_use",
        id="toolu_1",
        name=member,
        input=member_input,
        toolset_name="computer",
    )
    _, tool_calls = content_and_tool_calls_from_assistant_content_blocks(
        [block], [computer_tool_info()]
    )
    assert tool_calls == [
        ToolCall(
            id="toolu_1",
            function="computer",
            arguments={"action": member, **member_input},
        )
    ]


def test_inbound_member_name_without_toolset_is_not_translated() -> None:
    """A custom tool that happens to share a member name is dispatched as itself."""
    init_sample_anthropic_assistant_internal()
    block = ToolUseBlock(
        type="tool_use", id="toolu_1", name="left_click", input={"coordinate": [1, 2]}
    )
    tools = [
        computer_tool_info(),
        ToolInfo(
            name="left_click",
            description="custom",
            parameters=ToolParams(properties={"coordinate": ToolParam(type="array")}),
        ),
    ]
    _, tool_calls = content_and_tool_calls_from_assistant_content_blocks([block], tools)
    assert tool_calls == [
        ToolCall(id="toolu_1", function="left_click", arguments={"coordinate": [1, 2]})
    ]


def test_inbound_legacy_computer_tool_use_unchanged() -> None:
    init_sample_anthropic_assistant_internal()
    block = ToolUseBlock(
        type="tool_use",
        id="toolu_1",
        name="computer",
        input={"action": "left_click", "coordinate": [1, 2]},
    )
    _, tool_calls = content_and_tool_calls_from_assistant_content_blocks(
        [block], [computer_tool_info()]
    )
    assert tool_calls == [
        ToolCall(
            id="toolu_1",
            function="computer",
            arguments={"action": "left_click", "coordinate": [1, 2]},
        )
    ]


# ---------------------------------------------------------------------------
# Outbound: tool_result / tool_use replay carries toolset_name
# ---------------------------------------------------------------------------


async def test_outbound_image_result_carries_toolset_name() -> None:
    message = ChatMessageTool(
        content=[ContentImage(image=PNG_DATA_URI)],
        tool_call_id="toolu_1",
        function="computer",
    )
    param = await message_param(message, computer_toolset_call_ids={"toolu_1"})
    assert param["role"] == "user"
    block = first_block(param)
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "toolu_1"
    assert block["toolset_name"] == "computer"
    assert block["is_error"] is False
    content = list(block["content"])
    assert len(content) == 1 and content[0]["type"] == "image"


async def test_outbound_text_result_carries_toolset_name() -> None:
    message = ChatMessageTool(
        content=[ContentText(text="X=512, Y=384")],
        tool_call_id="toolu_1",
        function="computer",
    )
    param = await message_param(message, computer_toolset_call_ids={"toolu_1"})
    block = first_block(param)
    assert block["toolset_name"] == "computer"
    assert block["is_error"] is False
    assert list(block["content"]) == [{"type": "text", "text": "X=512, Y=384"}]


async def test_outbound_error_result_is_error_with_exact_text() -> None:
    message = ChatMessageTool(
        content="",
        tool_call_id="toolu_2",
        function="computer",
        error=ToolCallError("cancelled", NOT_EXECUTED),
    )
    param = await message_param(message, computer_toolset_call_ids={"toolu_2"})
    block = first_block(param)
    assert block["toolset_name"] == "computer"
    assert block["is_error"] is True
    assert block["content"] == NOT_EXECUTED


async def test_outbound_result_without_toolset_has_no_toolset_name() -> None:
    message = ChatMessageTool(content="OK", tool_call_id="toolu_1", function="computer")
    param = await message_param(message)
    block = first_block(param)
    assert "toolset_name" not in block


async def test_replay_computer_call_as_toolset_member() -> None:
    init_sample_anthropic_assistant_internal()
    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(
                id="toolu_1",
                function="computer",
                arguments={"action": "left_click", "coordinate": [1, 2]},
            )
        ],
    )
    params = await assistant_message_block_params(
        message, computer_toolset_call_ids={"toolu_1"}
    )
    tool_uses = [p for p in params if p["type"] == "tool_use"]
    assert tool_uses == [
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "left_click",
            "toolset_name": "computer",
            "input": {"coordinate": [1, 2]},
        }
    ]
    # the message's own arguments are left untouched
    assert message.tool_calls is not None
    assert message.tool_calls[0].arguments == {
        "action": "left_click",
        "coordinate": [1, 2],
    }


async def test_replay_computer_call_legacy_shape_without_toolset() -> None:
    init_sample_anthropic_assistant_internal()
    message = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(
                id="toolu_1",
                function="computer",
                arguments={"action": "left_click", "coordinate": [1, 2]},
            )
        ],
    )
    params = await assistant_message_block_params(message)
    tool_uses = [p for p in params if p["type"] == "tool_use"]
    assert tool_uses == [
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "computer",
            "input": {"action": "left_click", "coordinate": [1, 2]},
        }
    ]


# ---------------------------------------------------------------------------
# Request wiring: tools, message shapes, ordering and beta headers
# ---------------------------------------------------------------------------


async def _capture_generate(api: AnthropicAPI) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_perform(
        request: dict[str, Any],
        streaming: bool,
        tools: list[Any],
        config: GenerateConfig,
        pending_tool_uses: Any = None,
        pending_mcp_tool_uses: Any = None,
        span_recorder: Any = None,
    ) -> tuple[dict[str, Any], ModelOutput]:
        captured.update(request)
        return {}, ModelOutput.from_content(
            model=api.service_model_name(), content="ok"
        )

    init_sample_anthropic_assistant_internal()
    with patch.object(api, "_perform_request_and_continuations", fake_perform):
        await api.generate(
            input=[
                ChatMessageUser(content="Open the browser."),
                ChatMessageAssistant(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="toolu_1",
                            function="computer",
                            arguments={"action": "left_click", "coordinate": [1, 2]},
                        ),
                        ToolCall(
                            id="toolu_2",
                            function="computer",
                            arguments={"action": "screenshot"},
                        ),
                    ],
                ),
                ChatMessageTool(
                    content="OK", tool_call_id="toolu_1", function="computer"
                ),
                ChatMessageTool(
                    content=[ContentImage(image=PNG_DATA_URI)],
                    tool_call_id="toolu_2",
                    function="computer",
                ),
            ],
            tools=[computer_tool_info()],
            tool_choice="auto",
            config=GenerateConfig(max_tokens=64),
        )
    return captured


def _beta_header(request: dict[str, Any]) -> str:
    return str(request.get("extra_headers", {}).get("anthropic-beta", ""))


async def test_toolset_request_wiring() -> None:
    request = await _capture_generate(anthropic_api("claude-opus-5-5"))

    # toolset declared (no name / dimensions) and no computer-use beta header
    assert [tool["type"] for tool in request["tools"]] == [TOOLSET]
    assert "name" not in request["tools"][0]
    assert "computer-use" not in _beta_header(request)

    # assistant tool_use blocks replay as members
    assistant = request["messages"][1]
    tool_uses = [b for b in assistant["content"] if b["type"] == "tool_use"]
    assert [(b["name"], b["toolset_name"]) for b in tool_uses] == [
        ("left_click", "computer"),
        ("screenshot", "computer"),
    ]
    assert tool_uses[0]["input"] == {"coordinate": [1, 2]}
    assert tool_uses[1]["input"] == {}

    # both results land in one user message, in call order, with toolset_name
    results = request["messages"][2]
    assert results["role"] == "user"
    blocks = [b for b in results["content"] if b["type"] == "tool_result"]
    assert [b["tool_use_id"] for b in blocks] == ["toolu_1", "toolu_2"]
    assert all(b["toolset_name"] == "computer" for b in blocks)
    assert blocks[1]["content"][0]["type"] == "image"


async def test_legacy_request_wiring_unchanged() -> None:
    request = await _capture_generate(anthropic_api("claude-opus-5"))

    assert [tool["type"] for tool in request["tools"]] == [LEGACY]
    assert request["tools"][0]["name"] == "computer"
    assert "computer-use-2025-11-24" in _beta_header(request)

    assistant = request["messages"][1]
    tool_uses = [b for b in assistant["content"] if b["type"] == "tool_use"]
    assert [b["name"] for b in tool_uses] == ["computer", "computer"]
    assert all("toolset_name" not in b for b in tool_uses)
    assert tool_uses[0]["input"] == {"action": "left_click", "coordinate": [1, 2]}

    blocks = [
        b for b in request["messages"][2]["content"] if b["type"] == "tool_result"
    ]
    assert [b["tool_use_id"] for b in blocks] == ["toolu_1", "toolu_2"]
    assert all("toolset_name" not in b for b in blocks)


async def test_toolset_request_wiring_forced_on_opus_5() -> None:
    request = await _capture_generate(
        anthropic_api("claude-opus-5", computer_toolset=True)
    )
    assert [tool["type"] for tool in request["tools"]] == [TOOLSET]
    assert "computer-use" not in _beta_header(request)
    blocks = [
        b for b in request["messages"][2]["content"] if b["type"] == "tool_result"
    ]
    assert all(b["toolset_name"] == "computer" for b in blocks)


def test_inbound_member_without_computer_tool_keeps_member_name() -> None:
    """Without inspect's computer tool declared, a member call is not rewritten."""
    init_sample_anthropic_assistant_internal()
    block = ToolUseBlock(
        type="tool_use",
        id="toolu_1",
        name="left_click",
        input={"coordinate": [1, 2]},
        toolset_name="computer",
    )
    _, tool_calls = content_and_tool_calls_from_assistant_content_blocks([block], [])
    assert tool_calls == [
        ToolCall(
            id="toolu_1",
            function="left_click",
            arguments={"action": "left_click", "coordinate": [1, 2]},
        )
    ]


async def test_forced_computer_tool_choice_degrades_to_auto_with_toolset() -> None:
    """The toolset has no tool named `computer` to force, so the choice becomes auto."""
    from inspect_ai.tool import ToolFunction

    api = anthropic_api("claude-opus-5", computer_toolset=True)
    captured: dict[str, Any] = {}

    async def fake_perform(
        request: dict[str, Any],
        streaming: bool,
        tools: list[Any],
        config: GenerateConfig,
        pending_tool_uses: Any = None,
        pending_mcp_tool_uses: Any = None,
        span_recorder: Any = None,
    ) -> tuple[dict[str, Any], ModelOutput]:
        captured.update(request)
        return {}, ModelOutput.from_content(
            model=api.service_model_name(), content="ok"
        )

    init_sample_anthropic_assistant_internal()
    with patch.object(api, "_perform_request_and_continuations", fake_perform):
        output, _ = await api.generate(
            input=[ChatMessageUser(content="Take a screenshot.")],
            tools=[computer_tool_info()],
            tool_choice=ToolFunction(name="computer"),
            config=GenerateConfig(max_tokens=64),
        )
    assert captured["tool_choice"]["type"] == "auto"
    assert isinstance(output, ModelOutput) and output.metadata is not None
    assert output.metadata["tool_choice_degraded"] == {
        "requested": {"type": "tool", "name": "computer"},
        "used": {"type": "auto"},
    }


async def test_forced_computer_tool_choice_kept_with_legacy_tool() -> None:
    from inspect_ai.tool import ToolFunction

    api = anthropic_api("claude-opus-5")
    captured: dict[str, Any] = {}

    async def fake_perform(
        request: dict[str, Any],
        streaming: bool,
        tools: list[Any],
        config: GenerateConfig,
        pending_tool_uses: Any = None,
        pending_mcp_tool_uses: Any = None,
        span_recorder: Any = None,
    ) -> tuple[dict[str, Any], ModelOutput]:
        captured.update(request)
        return {}, ModelOutput.from_content(
            model=api.service_model_name(), content="ok"
        )

    init_sample_anthropic_assistant_internal()
    with patch.object(api, "_perform_request_and_continuations", fake_perform):
        output, _ = await api.generate(
            input=[ChatMessageUser(content="Take a screenshot.")],
            tools=[computer_tool_info()],
            tool_choice=ToolFunction(name="computer"),
            config=GenerateConfig(max_tokens=64),
        )
    assert captured["tool_choice"] == {"type": "tool", "name": "computer"}
    assert isinstance(output, ModelOutput)
    assert not (output.metadata or {}).get("tool_choice_degraded")


def test_inbound_member_name_wins_over_an_action_key_in_input() -> None:
    """Member inputs carry no `action` field; if one appears, the member name wins."""
    init_sample_anthropic_assistant_internal()
    block = ToolUseBlock(
        type="tool_use",
        id="toolu_1",
        name="left_click",
        input={"coordinate": [1, 2], "action": "type"},
        toolset_name="computer",
    )
    _, tool_calls = content_and_tool_calls_from_assistant_content_blocks(
        [block], [computer_tool_info()]
    )
    assert tool_calls is not None
    assert tool_calls[0].arguments == {"coordinate": [1, 2], "action": "left_click"}


# ---------------------------------------------------------------------------
# Batch marker: toolset member batches are fail-fast for execute_tools
# ---------------------------------------------------------------------------


def _message(*blocks: Any) -> Any:
    from anthropic.types import Message, Usage

    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-opus-5-5",
        content=list(blocks),
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


async def test_toolset_batch_marks_assistant_message_fail_fast() -> None:
    from inspect_ai.model._call_tools import TOOL_CALLS_FAIL_FAST
    from inspect_ai.model._providers.anthropic import model_output_from_message

    init_sample_anthropic_assistant_internal()
    message = _message(
        ToolUseBlock(
            type="tool_use",
            id="toolu_1",
            name="left_click",
            input={"coordinate": [1, 2]},
            toolset_name="computer",
        ),
        ToolUseBlock(
            type="tool_use",
            id="toolu_2",
            name="screenshot",
            input={},
            toolset_name="computer",
        ),
    )
    output, _ = await model_output_from_message(
        None, "claude-opus-5-5", message, [computer_tool_info()]
    )
    assistant = output.choices[0].message
    assert assistant.metadata is not None
    assert assistant.metadata[TOOL_CALLS_FAIL_FAST] == ["computer"]
    assert [tc.function for tc in assistant.tool_calls or []] == [
        "computer",
        "computer",
    ]


async def test_legacy_computer_call_is_not_marked_fail_fast() -> None:
    from inspect_ai.model._call_tools import TOOL_CALLS_FAIL_FAST
    from inspect_ai.model._providers.anthropic import model_output_from_message

    init_sample_anthropic_assistant_internal()
    message = _message(
        ToolUseBlock(
            type="tool_use",
            id="toolu_1",
            name="computer",
            input={"action": "left_click", "coordinate": [1, 2]},
        )
    )
    output, _ = await model_output_from_message(
        None, "claude-opus-5", message, [computer_tool_info()]
    )
    assistant = output.choices[0].message
    assert TOOL_CALLS_FAIL_FAST not in (assistant.metadata or {})
