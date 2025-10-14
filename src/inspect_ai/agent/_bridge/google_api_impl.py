from __future__ import annotations

from typing import Any

from google.genai.types import (
    Candidate,
    Content,
    FinishReason,
    FunctionCall,
    GenerateContentResponse,
    GenerateContentResponseUsageMetadata,
    Part,
    ToolConfig,
)
from google.genai.types import Tool as GoogleTool
from shortuuid import uuid

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


async def inspect_google_api_request_impl(
    json_data: dict[str, Any],
    web_search: WebSearchProviders,
    bridge: AgentBridge,
) -> GenerateContentResponse:
    # resolve model
    bridge_model_name = str(json_data.get("model", "inspect"))
    model = resolve_inspect_model(bridge_model_name)
    model_name = model.api.model_name

    # tools
    google_tools: list[GoogleTool] | None = json_data.get("tools", None)
    tools = tools_from_google_tools(google_tools, web_search)

    # tool choice
    google_tool_config: ToolConfig | None = json_data.get("toolConfig", None)
    tool_choice = tool_choice_from_google_tool_config(google_tool_config)

    # convert to inspect messages
    input: list[Content] = json_data.get("contents", [])
    debug_log("SCAFFOLD INPUT", input)

    messages = await messages_from_google_input(input, tools)
    debug_log("INSPECT MESSAGES", messages)

    # extract generate config (hoist instructions into system_message)
    config = generate_config_from_google(json_data)
    if config.system_message is not None:
        messages.insert(0, ChatMessageSystem(content=config.system_message))
        config.system_message = None

    # try to maintain id stability
    apply_message_ids(bridge, messages)

    # give inspect-level config priority over agent default config
    config = resolve_generate_config(model, config)

    # if there is a bridge filter give it a shot first
    output = await bridge_generate(bridge, model, messages, tools, tool_choice, config)

    debug_log("INSPECT OUTPUT", output.message)

    # update state if we have more messages than the last generation
    bridge._track_state(messages, output)

    # return response
    response = google_response_from_output(output, model_name)
    debug_log("SCAFFOLD RESPONSE", response)

    return response


def debug_log(caption: str, o: Any) -> None:
    # from inspect_ai._util.json import to_json_str_safe

    # print(caption)
    # print(to_json_str_safe(o))
    pass


def generate_config_from_google(json_data: dict[str, Any]) -> GenerateConfig:
    config = GenerateConfig()

    generation_config = json_data.get("generationConfig", {})
    config.temperature = generation_config.get("temperature", None)
    config.max_tokens = generation_config.get("maxOutputTokens", None)
    config.top_p = generation_config.get("topP", None)
    config.top_k = generation_config.get("topK", None)
    config.stop_seqs = generation_config.get("stopSequences", None)

    # System instructions
    system_instruction = json_data.get("systemInstruction", None)
    if system_instruction:
        if isinstance(system_instruction, dict):
            parts = system_instruction.get("parts", [])
            if parts:
                config.system_message = "\n".join(
                    part.get("text", "") for part in parts if "text" in part
                )
        elif isinstance(system_instruction, str):
            config.system_message = system_instruction

    # Thinking/reasoning configuration
    thinking_config = json_data.get("thinkingConfig", None)
    if thinking_config:
        thinking_budget = thinking_config.get("thinkingBudget", None)
        if thinking_budget is not None:
            config.reasoning_tokens = thinking_budget

    return config


def tools_from_google_tools(
    google_tools: list[GoogleTool] | None,
    web_search_providers: WebSearchProviders,
) -> list[ToolInfo | Tool]:
    tools: list[ToolInfo | Tool] = []

    for tool in google_tools or []:
        if tool.google_search is not None:
            # Gemini native web search - convert to Inspect web_search tool
            tools.append(web_search(web_search_providers))
        elif tool.function_declarations:
            for func_decl in tool.function_declarations:
                if func_decl.name is None:
                    continue
                tools.append(
                    ToolInfo(
                        name=func_decl.name,
                        description=func_decl.description or "",
                        parameters=ToolParams.model_validate(
                            func_decl.parameters.model_dump()
                            if func_decl.parameters
                            else {}
                        ),
                    )
                )

    return tools


def tool_choice_from_google_tool_config(
    tool_config: ToolConfig | None,
) -> ToolChoice | None:
    if tool_config is None or tool_config.function_calling_config is None:
        return None

    func_calling_config = tool_config.function_calling_config
    mode = func_calling_config.mode if func_calling_config.mode else "AUTO"

    match mode:
        case "AUTO" | "VALIDATED":
            return "auto"
        case "ANY":
            return "any"
        case "NONE":
            return "none"
        case _:
            # If specific function name, extract it
            if func_calling_config.allowed_function_names:
                allowed = func_calling_config.allowed_function_names
                if len(allowed) == 1:
                    return ToolFunction(name=allowed[0])
            return "auto"


async def messages_from_google_input(
    input: list[Content], tools: list[ToolInfo | Tool]
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    tool_names: dict[str, str] = {}  # tool_call_id -> function_name

    for content in input:
        role = content.role or "user"
        parts = content.parts or []

        if role == "model":  # Gemini uses "model" not "assistant"
            text_parts = []
            tool_calls: list[ToolCall] = []

            for part in parts:
                if part.text is not None:
                    text_parts.append(part.text)
                elif part.function_call is not None:
                    func_call = part.function_call
                    if func_call.name is None or func_call.args is None:
                        continue
                    tool_call_id = str(uuid())
                    tool_call = ToolCall(
                        id=tool_call_id,
                        function=func_call.name,
                        arguments=func_call.args,
                    )
                    tool_calls.append(tool_call)
                    tool_names[tool_call_id] = tool_call.function

            messages.append(
                ChatMessageAssistant(
                    content="\n".join(text_parts) if text_parts else "",
                    tool_calls=tool_calls if tool_calls else None,
                )
            )

        elif role == "user":
            pending_user_parts: list[str] = []

            for part in parts:
                if part.text is not None:
                    pending_user_parts.append(part.text)
                elif part.function_response is not None:
                    if pending_user_parts:
                        messages.append(
                            ChatMessageUser(content="\n".join(pending_user_parts))
                        )
                        pending_user_parts = []

                    func_response = part.function_response
                    if func_response.name is None:
                        continue
                    # Gemini uses function name as identifier
                    func_name = func_response.name
                    tool_call_id = next(
                        (
                            tid
                            for tid, fname in tool_names.items()
                            if fname == func_name
                        ),
                        func_name,
                    )
                    messages.append(
                        ChatMessageTool(
                            tool_call_id=tool_call_id,
                            function=func_name,
                            content=str(func_response.response or {}),
                        )
                    )

            if pending_user_parts:
                messages.append(ChatMessageUser(content="\n".join(pending_user_parts)))

    return messages


def google_response_from_output(
    output: ModelOutput,
    model_name: str,
) -> GenerateContentResponse:
    # Build parts from output message
    parts: list[Part] = []

    # Add text content
    if output.message.content:
        parts.append(Part(text=output.message.text))

    # Add function calls if present
    if output.message.tool_calls:
        for tool_call in output.message.tool_calls:
            parts.append(
                Part(
                    function_call=FunctionCall(
                        name=tool_call.function,
                        args=tool_call.arguments,
                    )
                )
            )

    # Build response structure
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(parts=parts, role="model"),
                finish_reason=google_finish_reason(output.stop_reason),
            )
        ],
        usage_metadata=google_usage(output.usage or ModelUsage()),
    )

    return response


def google_finish_reason(stop_reason: StopReason) -> FinishReason:
    match stop_reason:
        case "stop" | "tool_calls":  # Gemini uses STOP for function calls
            return FinishReason.STOP
        case "max_tokens" | "model_length":
            return FinishReason.MAX_TOKENS
        case "content_filter":
            return FinishReason.SAFETY
        case "unknown":
            return FinishReason.OTHER


def google_usage(usage: ModelUsage) -> GenerateContentResponseUsageMetadata:
    return GenerateContentResponseUsageMetadata(
        prompt_token_count=usage.input_tokens,
        candidates_token_count=usage.output_tokens,
        total_token_count=usage.input_tokens + usage.output_tokens,
    )
