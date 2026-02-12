from __future__ import annotations

import base64
import hashlib
import json
from logging import getLogger
from typing import Any, Literal

from shortuuid import uuid

from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput, ModelUsage, StopReason
from inspect_ai.model._reasoning import (
    parse_content_with_reasoning,
    reasoning_to_think_tag,
)
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

    debug_log("SCAFFOLD INPUT", contents)

    # translate tools
    tools = tools_from_google_tools(
        google_tools, web_search_providers, code_execution_providers
    )

    # translate tool choice
    tool_choice = tool_choice_from_google_tool_config(tool_config)

    # translate messages
    messages = messages_from_google_contents(contents, system_instruction)
    debug_log("INSPECT MESSAGES", messages)

    # extract generate config
    config = generate_config_from_google(generation_config)

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

    debug_log("INSPECT OUTPUT", output.message)

    # update state if we have more messages than the last generation
    bridge._track_state(messages, output)

    # translate response to Gemini format
    response = gemini_response_from_output(output, model.api.model_name)
    debug_log("SCAFFOLD RESPONSE", response)

    return response


def debug_log(caption: str, o: Any) -> None:
    # from inspect_ai._util.json import to_json_str_safe

    # print(caption)
    # print(to_json_str_safe(o))
    pass


def generate_config_from_google(generation_config: dict[str, Any]) -> GenerateConfig:
    config = GenerateConfig()
    config.temperature = generation_config.get("temperature")
    config.max_tokens = generation_config.get("maxOutputTokens")
    config.top_p = generation_config.get("topP", generation_config.get("top_p"))
    config.top_k = generation_config.get("topK", generation_config.get("top_k"))
    config.stop_seqs = generation_config.get(
        "stopSequences", generation_config.get("stop_sequences")
    )

    # NOTE: We deliberately do NOT set config.system_message from system_instruction here.
    # The system_instruction is already converted to ChatMessageSystem messages in
    # messages_from_google_contents(). Setting config.system_message would cause
    # model.generate() to prepend a duplicate system message.

    return config


def tools_from_google_tools(
    google_tools: list[dict[str, Any]] | None,
    web_search_providers: WebSearchProviders,
    code_execution_providers: CodeExecutionProviders,
) -> list[ToolInfo | Tool]:
    tools: list[ToolInfo | Tool] = []

    for google_tool in google_tools or []:
        if "functionDeclarations" in google_tool:
            for func_decl in google_tool["functionDeclarations"]:
                # Parameters can be in "parameters" or "parametersJsonSchema"
                parameters = func_decl.get(
                    "parameters", func_decl.get("parametersJsonSchema", {})
                )
                # Convert Google SDK enum types to strings before validation
                parameters = _convert_google_enums(parameters)
                tools.append(
                    ToolInfo(
                        name=func_decl.get("name", ""),
                        description=func_decl.get("description", ""),
                        parameters=ToolParams.model_validate(parameters)
                        if parameters
                        else ToolParams(),
                    )
                )
        elif "googleSearch" in google_tool:
            tools.append(web_search(web_search_providers))
        elif "codeExecution" in google_tool:
            tools.append(code_execution(providers=code_execution_providers))
        elif "googleSearchRetrieval" in google_tool:
            # Google Search Retrieval (grounding)
            tools.append(web_search(web_search_providers))

    return tools


def tool_choice_from_google_tool_config(
    tool_config: dict[str, Any] | None,
) -> ToolChoice | None:
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
            allowed = function_calling_config.get("allowedFunctionNames", [])
            if allowed and len(allowed) == 1:
                return ToolFunction(name=allowed[0])
            return "auto"


def messages_from_google_contents(
    contents: list[dict[str, Any]],
    system_instruction: dict[str, Any] | list[Any] | None,
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []

    # track system prompt text so we can strip duplicate prefixes from user messages
    system_prompt_text: str | None = None

    if system_instruction:
        if isinstance(system_instruction, dict):
            parts = system_instruction.get("parts", [])
            system_text = _extract_text_from_parts(parts)
            if system_text:
                messages.append(ChatMessageSystem(content=system_text))
                system_prompt_text = system_text
        elif isinstance(system_instruction, list):
            texts = []
            for item in system_instruction:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    texts.append(item["text"])
            if texts:
                seen = set()
                unique_texts = []
                for t in texts:
                    if t not in seen:
                        seen.add(t)
                        unique_texts.append(t)
                combined_text = "\n\n".join(unique_texts)
                messages.append(ChatMessageSystem(content=combined_text))
                system_prompt_text = combined_text

    # prepend a user message if history starts with model function calls
    # (Gemini API requires function call turns to follow a user turn)
    if contents:
        first_content = contents[0]
        first_role = first_content.get("role", "user")
        if first_role == "model":
            first_parts = first_content.get("parts", [])
            has_function_calls = any(
                isinstance(p, dict) and ("functionCall" in p or "function_call" in p)
                for p in first_parts
            )
            if has_function_calls:
                messages.append(
                    ChatMessageUser(content="(continuing from previous context)")
                )
                logger.debug(
                    "Prepending user message before model function call to satisfy Gemini API constraints"
                )

    # track tool call IDs by function name for matching with tool results
    pending_tool_calls: dict[str, list[str]] = {}

    for content in contents:
        role = content.get("role", "user")
        parts = content.get("parts", [])

        if role == "user":
            user_content, tool_messages = _extract_user_parts(parts, pending_tool_calls)
            if user_content:
                # strip duplicate system prompt prefix
                user_content = _strip_system_prompt_prefix(
                    user_content, system_prompt_text
                )
                if user_content:
                    messages.append(ChatMessageUser(content=user_content))
            messages.extend(tool_messages)

        elif role == "model":
            assistant_content, tool_calls = _extract_model_parts(parts)

            pending_tool_calls.clear()
            for tc in tool_calls:
                if tc.function not in pending_tool_calls:
                    pending_tool_calls[tc.function] = []
                pending_tool_calls[tc.function].append(tc.id)

            messages.append(
                ChatMessageAssistant(
                    content=assistant_content if assistant_content else "",
                    tool_calls=tool_calls if tool_calls else None,
                )
            )

    return messages


def _extract_text_from_parts(parts: list[dict[str, Any]]) -> str:
    texts = []
    for part in parts:
        if isinstance(part, dict) and "text" in part:
            texts.append(part["text"])
        elif isinstance(part, str):
            texts.append(part)
    return "".join(texts)


def _strip_system_prompt_prefix(
    user_content: list[Content] | str,
    system_prompt: str | None,
) -> list[Content] | str | None:
    """Strip duplicate system prompt prefix from user message content.

    Gemini CLI sometimes prepends the full system prompt to user messages,
    particularly when sending continuation prompts.
    """
    if not system_prompt:
        return user_content

    if isinstance(user_content, str):
        if user_content.startswith(system_prompt):
            stripped = user_content[len(system_prompt) :].lstrip("\n\r\t ")
            return stripped if stripped else None
        return user_content

    if isinstance(user_content, list) and user_content:
        first_content = user_content[0]
        if isinstance(first_content, ContentText):
            if first_content.text.startswith(system_prompt):
                stripped_text = first_content.text[len(system_prompt) :].lstrip(
                    "\n\r\t "
                )
                if stripped_text:
                    return [ContentText(text=stripped_text)] + list(user_content[1:])
                elif len(user_content) > 1:
                    return list(user_content[1:])
                else:
                    return None
        return user_content

    return user_content


def _extract_user_parts(
    parts: list[dict[str, Any]],
    pending_tool_calls: dict[str, list[str]],
) -> tuple[list[Content] | str | None, list[ChatMessageTool]]:
    # pending_tool_calls maps function_name -> list of call_ids from the previous
    # model message, used to match functionResponse with the correct tool_use_id.
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
            inline_data = part.get("inlineData", part.get("inline_data", {}))
            mime_type = inline_data.get("mimeType", inline_data.get("mime_type", ""))
            data = inline_data.get("data", "")
            if mime_type.startswith("image/"):
                content_parts.append(
                    ContentImage(image=f"data:{mime_type};base64,{data}")
                )

        elif "functionResponse" in part or "function_response" in part:
            func_response = part.get(
                "functionResponse", part.get("function_response", {})
            )
            func_name = func_response.get("name", "")
            response = func_response.get("response", {})

            if func_name in pending_tool_calls and pending_tool_calls[func_name]:
                call_id = pending_tool_calls[func_name].pop(0)
            else:
                call_id = f"call_{func_name}_{uuid()[:8]}"
                logger.warning(
                    f"No pending tool call found for function '{func_name}', "
                    f"generating new call_id: {call_id}"
                )

            response_content = (
                json.dumps(response) if isinstance(response, dict) else str(response)
            )

            tool_messages.append(
                ChatMessageTool(
                    tool_call_id=call_id,
                    function=func_name,
                    content=response_content,
                )
            )

    if len(content_parts) == 1 and isinstance(content_parts[0], ContentText):
        return content_parts[0].text, tool_messages
    if content_parts:
        return content_parts, tool_messages
    return None, tool_messages


def _extract_model_parts(
    parts: list[dict[str, Any]],
) -> tuple[list[Content] | None, list[ToolCall]]:
    """Extract assistant content and function calls from model parts.

    Returns content as a list (never simplified to string) for message ID stability.
    """
    content_parts: list[Content] = []
    tool_calls: list[ToolCall] = []
    first_fc_signature_captured = False

    embedded_capsule = None
    for part in parts:
        if isinstance(part, dict) and "text" in part:
            _, capsule = parse_content_with_reasoning(part["text"])
            if capsule is not None:
                embedded_capsule = capsule
                break

    for part_idx, part in enumerate(parts):
        if not isinstance(part, dict):
            if isinstance(part, str):
                content_parts.append(ContentText(text=part))
            continue

        if "text" in part:
            text = part["text"]
            remaining_text, capsule = parse_content_with_reasoning(text)
            if capsule is not None:
                if remaining_text:
                    content_parts.append(ContentText(text=remaining_text))
                continue
            if text == "(no content)":
                continue
            content_parts.append(ContentText(text=text))

        elif "functionCall" in part or "function_call" in part:
            func_call = part.get("functionCall", part.get("function_call", {}))
            func_name = func_call.get("name", "")
            args = func_call.get("args", {})

            thought_sig = part.get("thoughtSignature", part.get("thought_signature"))

            if not thought_sig and not first_fc_signature_captured:
                if embedded_capsule:
                    thought_sig = embedded_capsule.reasoning

            if thought_sig and not first_fc_signature_captured:
                if isinstance(thought_sig, str):
                    sig_str = thought_sig
                else:
                    sig_str = base64.b64encode(thought_sig).decode()

                if embedded_capsule and embedded_capsule.reasoning == sig_str:
                    content_parts.append(
                        ContentReasoning(
                            reasoning=embedded_capsule.reasoning,
                            signature=embedded_capsule.signature,
                            redacted=embedded_capsule.redacted,
                            summary=embedded_capsule.summary,
                        )
                    )
                else:
                    content_parts.append(
                        ContentReasoning(
                            reasoning=sig_str,
                            redacted=True,
                        )
                    )
                first_fc_signature_captured = True

            if not isinstance(args, dict):
                args = {"value": args}

            # deterministic call ID for message ID stability
            args_str = json.dumps(args, sort_keys=True) if args else ""
            call_hash = hashlib.md5(
                f"{func_name}:{args_str}:{part_idx}".encode()
            ).hexdigest()[:8]
            call_id = f"call_{func_name}_{call_hash}"

            tool_calls.append(
                ToolCall(
                    id=call_id,
                    function=func_name,
                    arguments=args,
                    type="function",
                )
            )

    if content_parts:
        return content_parts, tool_calls
    return None, tool_calls


def gemini_response_from_output(output: ModelOutput, model_name: str) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    working_reasoning_block: ContentReasoning | None = None

    if output.message.content:
        if isinstance(output.message.content, str):
            parts.append({"text": output.message.content})
        else:
            for c in output.message.content:
                if isinstance(c, ContentText):
                    if c.text:
                        parts.append({"text": c.text})
                elif isinstance(c, ContentReasoning):
                    if c.redacted and c.reasoning:
                        working_reasoning_block = c

    if output.message.tool_calls:
        for idx, tc in enumerate(output.message.tool_calls):
            if isinstance(tc.arguments, str):
                try:
                    args = json.loads(tc.arguments)
                except json.JSONDecodeError:
                    args = {"raw": tc.arguments}
            else:
                args = tc.arguments

            fc_part: dict[str, Any] = {
                "functionCall": {"name": tc.function, "args": args}
            }

            if idx == 0 and working_reasoning_block is not None:
                fc_part["thoughtSignature"] = working_reasoning_block.reasoning

            parts.append(fc_part)

    # Embed reasoning as a <think> tag text part so it survives the CLI's history
    # reconstruction (which strips API-level thoughtSignature but preserves text).
    if working_reasoning_block is not None:
        think_tag = reasoning_to_think_tag(working_reasoning_block)
        insert_pos = next((i for i, p in enumerate(parts) if "functionCall" in p), 0)
        parts.insert(insert_pos, {"text": think_tag})

    if not parts:
        parts.append({"text": ""})

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

    # Add convenience text field if there's text content (excluding embedded <think> tags)
    text_content = "".join(
        p.get("text", "")
        for p in parts
        if isinstance(p, dict)
        and "text" in p
        and not p["text"].strip().startswith("<think")
    )
    if text_content:
        response["text"] = text_content

    return response


def gemini_finish_reason(
    stop_reason: StopReason,
) -> Literal["STOP", "MAX_TOKENS", "SAFETY"]:
    match stop_reason:
        case "stop" | "tool_calls" | "unknown":
            return "STOP"
        case "max_tokens" | "model_length":
            return "MAX_TOKENS"
        case "content_filter":
            return "SAFETY"


def gemini_usage_metadata(usage: ModelUsage | None) -> dict[str, int]:
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


def _convert_google_enums(obj: Any) -> Any:
    """Convert Google SDK enum types to their string values.

    Google's genai SDK uses enum classes (e.g., Type.OBJECT, Type.STRING) for type
    fields, but ToolParams expects string literals ("object", "string"). This function
    recursively converts enum values to lowercase strings.
    """
    if isinstance(obj, dict):
        return {k: _convert_google_enums(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_google_enums(item) for item in obj]
    elif hasattr(obj, "value"):  # Enum-like object
        return str(obj.value).lower()
    return obj
