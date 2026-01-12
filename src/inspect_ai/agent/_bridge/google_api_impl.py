"""Google Gemini API translation for agent bridge.

Translates between Google's Gemini API format and Inspect's ChatMessage format.
Based on LiteLLM's GoogleGenAIAdapter implementation.

Gemini API format:
- Input: contents[] with role ("user"/"model") and parts[] (text, functionCall, functionResponse)
- System: systemInstruction with parts[]
- Tools: tools[] with functionDeclarations[]
- Output: candidates[] with content.parts[] and finishReason

Inspect format:
- Input: ChatMessage[] (ChatMessageUser, ChatMessageAssistant, ChatMessageTool, ChatMessageSystem)
- Tools: ToolInfo[]
- Output: ModelOutput with ChatMessageAssistant
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any

from shortuuid import uuid

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput, ModelUsage, StopReason
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.tool._tools._code_execution import (
    CodeExecutionProviders,
    code_execution,
)
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
    web_search,
)

from .types import AgentBridge
from .util import (
    apply_message_ids,
    bridge_generate,
    resolve_generate_config,
    resolve_inspect_model,
)

logger = getLogger(__name__)


async def inspect_google_api_request_impl(
    json_data: dict[str, Any],
    web_search_providers: WebSearchProviders,
    code_execution_providers: CodeExecutionProviders,
    bridge: AgentBridge,
) -> dict[str, Any]:
    """Process Google Gemini API request and return Gemini-format response."""
    # resolve model
    bridge_model_name = str(json_data.get("model", "inspect"))
    model = resolve_inspect_model(bridge_model_name)

    # extract request components
    contents: list[dict[str, Any]] = json_data.get("contents", [])
    system_instruction: dict[str, Any] | None = json_data.get(
        "systemInstruction", json_data.get("system_instruction")
    )
    google_tools: list[dict[str, Any]] | None = json_data.get("tools")
    tool_config: dict[str, Any] | None = json_data.get(
        "toolConfig", json_data.get("tool_config")
    )
    generation_config: dict[str, Any] = json_data.get(
        "generationConfig", json_data.get("generation_config", {})
    )

    # translate tools
    tools = tools_from_google_tools(
        google_tools, web_search_providers, code_execution_providers
    )

    # translate tool choice
    tool_choice = tool_choice_from_google_tool_config(tool_config)

    # translate messages
    messages = messages_from_google_contents(contents, system_instruction)

    # extract generate config
    config = generate_config_from_google(generation_config, json_data)

    # try to maintain id stability
    apply_message_ids(bridge, messages)

    # give inspect-level config priority over agent default config
    config = resolve_generate_config(model, config)

    # generate via bridge
    output, c_message = await bridge_generate(
        bridge, model, messages, tools, tool_choice, config
    )
    if c_message is not None:
        messages.append(c_message)

    # update state if we have more messages than the last generation
    bridge._track_state(messages, output)

    # translate response to Gemini format
    return gemini_response_from_output(output, model.api.model_name)


def generate_config_from_google(
    generation_config: dict[str, Any], json_data: dict[str, Any]
) -> GenerateConfig:
    """Extract GenerateConfig from Google API parameters."""
    config = GenerateConfig()

    # From generationConfig
    if "temperature" in generation_config:
        config.temperature = generation_config["temperature"]
    if "maxOutputTokens" in generation_config:
        config.max_tokens = generation_config["maxOutputTokens"]
    if "topP" in generation_config:
        config.top_p = generation_config["topP"]
    if "topK" in generation_config:
        config.top_k = generation_config["topK"]
    if "stopSequences" in generation_config:
        config.stop_seqs = generation_config["stopSequences"]

    # System instruction from top level
    system_instruction = json_data.get(
        "systemInstruction", json_data.get("system_instruction")
    )
    if system_instruction:
        parts = system_instruction.get("parts", [])
        if parts and isinstance(parts[0], dict) and "text" in parts[0]:
            config.system_message = parts[0]["text"]

    return config


def tools_from_google_tools(
    google_tools: list[dict[str, Any]] | None,
    web_search_providers: WebSearchProviders,
    code_execution_providers: CodeExecutionProviders,
) -> list[ToolInfo | Tool]:
    """Translate Google tools format to Inspect tools."""
    tools: list[ToolInfo | Tool] = []

    for tool in google_tools or []:
        if "functionDeclarations" in tool:
            # Standard function declarations
            for func_decl in tool["functionDeclarations"]:
                # Parameters can be in "parameters" or "parametersJsonSchema"
                parameters = func_decl.get(
                    "parameters", func_decl.get("parametersJsonSchema", {})
                )
                tools.append(
                    ToolInfo(
                        name=func_decl.get("name", ""),
                        description=func_decl.get("description", ""),
                        parameters=ToolParams.model_validate(parameters)
                        if parameters
                        else ToolParams(),
                    )
                )
        elif "googleSearch" in tool:
            # Google Search tool
            tools.append(web_search(web_search_providers))
        elif "codeExecution" in tool:
            # Code execution tool
            tools.append(code_execution(providers=code_execution_providers))
        elif "googleSearchRetrieval" in tool:
            # Google Search Retrieval (grounding)
            tools.append(web_search(web_search_providers))

    return tools


def tool_choice_from_google_tool_config(
    tool_config: dict[str, Any] | None,
) -> ToolChoice | None:
    """Translate Google toolConfig to Inspect tool choice."""
    if not tool_config:
        return None

    function_calling_config = tool_config.get("functionCallingConfig", {})
    mode = function_calling_config.get("mode", "AUTO")

    match mode:
        case "AUTO":
            return "auto"
        case "ANY":
            return "any"
        case "NONE":
            return "none"
        case _:
            # Check for allowed function names (specific tool)
            allowed = function_calling_config.get("allowedFunctionNames", [])
            if allowed and len(allowed) == 1:
                return ToolFunction(name=allowed[0])
            return "auto"


def messages_from_google_contents(
    contents: list[dict[str, Any]],
    system_instruction: dict[str, Any] | None,
) -> list[ChatMessage]:
    """Translate Google contents format to Inspect messages."""
    messages: list[ChatMessage] = []

    # Handle system instruction
    if system_instruction:
        parts = system_instruction.get("parts", [])
        system_text = _extract_text_from_parts(parts)
        if system_text:
            messages.append(ChatMessageSystem(content=system_text))

    # Track function names by call ID for tool results
    function_names: dict[str, str] = {}

    for content in contents:
        role = content.get("role", "user")
        parts = content.get("parts", [])

        if role == "user":
            # Handle user messages and function responses
            user_content, tool_messages = _extract_user_parts(parts)
            if user_content:
                messages.append(ChatMessageUser(content=user_content))
            messages.extend(tool_messages)

        elif role == "model":
            # Handle model/assistant messages with potential function calls
            assistant_content, tool_calls = _extract_model_parts(parts)

            # Record function names for later tool results
            for tc in tool_calls:
                function_names[tc.id] = tc.function

            # Build assistant message - content defaults to empty string if None
            messages.append(
                ChatMessageAssistant(
                    content=assistant_content if assistant_content else "",
                    tool_calls=tool_calls if tool_calls else None,
                )
            )

    return messages


def _extract_text_from_parts(parts: list[dict[str, Any]]) -> str:
    """Extract combined text from parts."""
    texts = []
    for part in parts:
        if isinstance(part, dict) and "text" in part:
            texts.append(part["text"])
        elif isinstance(part, str):
            texts.append(part)
    return "".join(texts)


def _extract_user_parts(
    parts: list[dict[str, Any]],
) -> tuple[list[Content] | str | None, list[ChatMessageTool]]:
    """Extract user content and function responses from parts."""
    content_parts: list[Content] = []
    tool_messages: list[ChatMessageTool] = []

    for part in parts:
        if not isinstance(part, dict):
            if isinstance(part, str):
                content_parts.append(ContentText(text=part))
            continue

        if "text" in part:
            content_parts.append(ContentText(text=part["text"]))

        elif "inlineData" in part or "inline_data" in part:
            # Handle inline image/media data
            inline_data = part.get("inlineData", part.get("inline_data", {}))
            mime_type = inline_data.get("mimeType", inline_data.get("mime_type", ""))
            data = inline_data.get("data", "")
            if mime_type.startswith("image/"):
                content_parts.append(
                    ContentImage(image=f"data:{mime_type};base64,{data}")
                )

        elif "functionResponse" in part or "function_response" in part:
            # Function response -> ChatMessageTool
            func_response = part.get(
                "functionResponse", part.get("function_response", {})
            )
            func_name = func_response.get("name", "")
            response = func_response.get("response", {})

            # Generate a call ID based on function name
            call_id = f"call_{func_name}_{uuid()[:8]}"

            # Serialize response to string if it's a dict
            if isinstance(response, dict):
                response_content = json.dumps(response)
            else:
                response_content = str(response)

            tool_messages.append(
                ChatMessageTool(
                    tool_call_id=call_id,
                    function=func_name,
                    content=response_content,
                )
            )

    # Simplify content if only one text part
    if len(content_parts) == 1 and isinstance(content_parts[0], ContentText):
        return content_parts[0].text, tool_messages
    elif content_parts:
        return content_parts, tool_messages
    else:
        return None, tool_messages


def _extract_model_parts(
    parts: list[dict[str, Any]],
) -> tuple[list[Content] | str | None, list[ToolCall]]:
    """Extract assistant content and function calls from model parts."""
    content_parts: list[Content] = []
    tool_calls: list[ToolCall] = []

    for part in parts:
        if not isinstance(part, dict):
            if isinstance(part, str):
                content_parts.append(ContentText(text=part))
            continue

        if "text" in part:
            content_parts.append(ContentText(text=part["text"]))

        elif "functionCall" in part or "function_call" in part:
            # Function call -> ToolCall
            func_call = part.get("functionCall", part.get("function_call", {}))
            func_name = func_call.get("name", "")
            args = func_call.get("args", {})

            # Generate a unique call ID
            call_id = f"call_{func_name}_{uuid()[:8]}"

            # Ensure args is a dict
            if not isinstance(args, dict):
                args = {"value": args}

            tool_calls.append(
                ToolCall(
                    id=call_id,
                    function=func_name,
                    arguments=args,
                    type="function",
                )
            )

    # Simplify content if only one text part
    if len(content_parts) == 1 and isinstance(content_parts[0], ContentText):
        return content_parts[0].text, tool_calls
    elif content_parts:
        return content_parts, tool_calls
    else:
        return None, tool_calls


def gemini_response_from_output(output: ModelOutput, model_name: str) -> dict[str, Any]:
    """Translate Inspect ModelOutput to Google Gemini API response format."""
    parts: list[dict[str, Any]] = []

    # Add text content
    if output.message.content:
        if isinstance(output.message.content, str):
            if output.message.content:
                parts.append({"text": output.message.content})
        else:
            for c in output.message.content:
                if isinstance(c, ContentText):
                    if c.text:
                        parts.append({"text": c.text})

    # Add function calls
    if output.message.tool_calls:
        for tc in output.message.tool_calls:
            # Parse arguments back to dict
            if isinstance(tc.arguments, str):
                try:
                    args = json.loads(tc.arguments)
                except json.JSONDecodeError:
                    args = {"raw": tc.arguments}
            else:
                args = tc.arguments

            parts.append({"functionCall": {"name": tc.function, "args": args}})

    # Ensure at least empty text part if no content
    if not parts:
        parts.append({"text": ""})

    # Build response
    response: dict[str, Any] = {
        "candidates": [
            {
                "content": {"parts": parts, "role": "model"},
                "finishReason": gemini_finish_reason(output.stop_reason),
                "index": 0,
                "safetyRatings": [],
            }
        ],
        "usageMetadata": gemini_usage_metadata(output.usage),
        "modelVersion": model_name,
    }

    # Add convenience text field if there's text content
    text_content = "".join(
        p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p
    )
    if text_content:
        response["text"] = text_content

    return response


def gemini_finish_reason(stop_reason: StopReason) -> str:
    """Map Inspect stop reason to Gemini finish reason."""
    mapping: dict[StopReason, str] = {
        "stop": "STOP",
        "max_tokens": "MAX_TOKENS",
        "model_length": "MAX_TOKENS",
        "tool_calls": "STOP",  # Gemini uses STOP for tool calls too
        "content_filter": "SAFETY",
        "unknown": "STOP",
    }
    return mapping.get(stop_reason, "STOP")


def gemini_usage_metadata(usage: ModelUsage | None) -> dict[str, int]:
    """Create Gemini usageMetadata from Inspect ModelUsage."""
    if usage is None:
        return {
            "promptTokenCount": 0,
            "candidatesTokenCount": 0,
            "totalTokenCount": 0,
        }
    return {
        "promptTokenCount": usage.input_tokens,
        "candidatesTokenCount": usage.output_tokens,
        "totalTokenCount": usage.total_tokens,
    }
