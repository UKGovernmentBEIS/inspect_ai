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

import base64
import hashlib
import json
from logging import getLogger
from typing import Any

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

    # translate tools
    tools = tools_from_google_tools(
        google_tools, web_search_providers, code_execution_providers
    )

    # translate tool choice
    tool_choice = tool_choice_from_google_tool_config(tool_config)

    # translate messages
    messages = messages_from_google_contents(contents, system_instruction)

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

    # update state if we have more messages than the last generation
    bridge._track_state(messages, output)

    # translate response to Gemini format
    return gemini_response_from_output(output, model.api.model_name)


def generate_config_from_google(generation_config: dict[str, Any]) -> GenerateConfig:
    """Extract GenerateConfig from Google API parameters."""
    config = GenerateConfig()

    # From generationConfig
    if "temperature" in generation_config:
        config.temperature = generation_config["temperature"]
    if "maxOutputTokens" in generation_config:
        config.max_tokens = generation_config["maxOutputTokens"]
    # Check both camelCase (Gemini) and snake_case variants
    if "topP" in generation_config or "top_p" in generation_config:
        config.top_p = generation_config.get("topP", generation_config.get("top_p"))
    if "topK" in generation_config or "top_k" in generation_config:
        config.top_k = generation_config.get("topK", generation_config.get("top_k"))
    if "stopSequences" in generation_config or "stop_sequences" in generation_config:
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
    system_instruction: dict[str, Any] | list[Any] | None,
) -> list[ChatMessage]:
    """Translate Google contents format to Inspect messages."""
    messages: list[ChatMessage] = []

    # Extract system prompt text for deduplication
    # Gemini CLI sometimes includes the system prompt as a prefix in user messages
    # (e.g., when sending continuation prompts). We detect and strip these duplicates.
    system_prompt_text: str | None = None

    # Handle system instruction (can be dict with "parts" or list of strings)
    if system_instruction:
        if isinstance(system_instruction, dict):
            # Standard format: {"parts": [{"text": "..."}]}
            parts = system_instruction.get("parts", [])
            system_text = _extract_text_from_parts(parts)
            if system_text:
                messages.append(ChatMessageSystem(content=system_text))
                system_prompt_text = system_text
        elif isinstance(system_instruction, list):
            # List format: ["text1", "text2", ...] or [{"text": "..."}, ...]
            # Combine all items into a single system message
            texts = []
            for item in system_instruction:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    texts.append(item["text"])
            if texts:
                # Use first unique text only to avoid duplicates
                seen = set()
                unique_texts = []
                for t in texts:
                    if t not in seen:
                        seen.add(t)
                        unique_texts.append(t)
                combined_text = "\n\n".join(unique_texts)
                messages.append(ChatMessageSystem(content=combined_text))
                system_prompt_text = combined_text

    # Gemini API requires that function call turns come after a user turn or
    # function response turn. If the CLI's history reconstruction starts with
    # a model message (common with --resume), we need to prepend a user message.
    # This happens when the CLI drops the initial user prompt from its history.
    if contents:
        first_content = contents[0]
        first_role = first_content.get("role", "user")
        if first_role == "model":
            # Check if the first model message has function calls
            first_parts = first_content.get("parts", [])
            has_function_calls = any(
                isinstance(p, dict) and ("functionCall" in p or "function_call" in p)
                for p in first_parts
            )
            if has_function_calls:
                # Prepend a placeholder user message to satisfy API constraints
                messages.append(
                    ChatMessageUser(content="(continuing from previous context)")
                )
                logger.debug(
                    "Prepending user message before model function call to satisfy Gemini API constraints"
                )

    # Track tool call IDs by function name for matching with tool results
    # Maps function_name -> list of call_ids (in order, for multiple calls to same function)
    pending_tool_calls: dict[str, list[str]] = {}

    for content in contents:
        role = content.get("role", "user")
        parts = content.get("parts", [])

        if role == "user":
            # Handle user messages and function responses
            user_content, tool_messages = _extract_user_parts(parts, pending_tool_calls)
            if user_content:
                # Strip duplicate system prompt prefix from user messages
                # Gemini CLI sometimes prepends the system prompt to continuation messages
                user_content = _strip_system_prompt_prefix(
                    user_content, system_prompt_text
                )
                if user_content:  # Only add if there's content after stripping
                    messages.append(ChatMessageUser(content=user_content))
            messages.extend(tool_messages)

        elif role == "model":
            # Handle model/assistant messages with potential function calls
            assistant_content, tool_calls = _extract_model_parts(parts)

            # Record tool call IDs for later matching with tool results
            # Clear pending calls since new model turn means new tool calls
            pending_tool_calls.clear()
            for tc in tool_calls:
                if tc.function not in pending_tool_calls:
                    pending_tool_calls[tc.function] = []
                pending_tool_calls[tc.function].append(tc.id)

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


def _strip_system_prompt_prefix(
    user_content: list[Content] | str,
    system_prompt: str | None,
) -> list[Content] | str | None:
    """Strip duplicate system prompt prefix from user message content.

    Gemini CLI sometimes prepends the full system prompt to user messages,
    particularly when sending continuation prompts (e.g., "[System] You haven't
    called the done tool yet..."). This creates duplicate system prompts in the
    trajectory and wastes tokens.

    This function detects when user content starts with the system prompt and
    strips it, leaving only the actual user content.

    Args:
        user_content: The user message content (string or list of Content)
        system_prompt: The system prompt text to check for and strip

    Returns:
        The user content with system prompt prefix stripped, or None if
        the content was entirely the system prompt
    """
    if not system_prompt:
        return user_content

    # Handle string content
    if isinstance(user_content, str):
        if user_content.startswith(system_prompt):
            # Strip the system prompt and any leading whitespace/newlines
            stripped = user_content[len(system_prompt) :].lstrip("\n\r\t ")
            return stripped if stripped else None
        return user_content

    # Handle list of Content
    if isinstance(user_content, list) and user_content:
        first_content = user_content[0]
        if isinstance(first_content, ContentText):
            if first_content.text.startswith(system_prompt):
                # Strip the system prompt prefix
                stripped_text = first_content.text[len(system_prompt) :].lstrip(
                    "\n\r\t "
                )
                if stripped_text:
                    # Replace first content with stripped version
                    new_content = [ContentText(text=stripped_text)] + list(
                        user_content[1:]
                    )
                    return new_content if new_content else None
                elif len(user_content) > 1:
                    # First content was only the system prompt, return rest
                    return list(user_content[1:])
                else:
                    # Entire content was just the system prompt
                    return None
        return user_content

    return user_content


def _extract_user_parts(
    parts: list[dict[str, Any]],
    pending_tool_calls: dict[str, list[str]],
) -> tuple[list[Content] | str | None, list[ChatMessageTool]]:
    """Extract user content and function responses from parts.

    Args:
        parts: The parts from a user message
        pending_tool_calls: Maps function_name -> list of call_ids from the previous
            model message. Used to match functionResponse with the correct tool_use_id.
    """
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

            # Use the matching call_id from the previous model message
            # Pop from the front of the list to maintain order for multiple calls
            if func_name in pending_tool_calls and pending_tool_calls[func_name]:
                call_id = pending_tool_calls[func_name].pop(0)
            else:
                # Fallback: generate a new ID (shouldn't happen in normal flow)
                call_id = f"call_{func_name}_{uuid()[:8]}"
                logger.warning(
                    f"No pending tool call found for function '{func_name}', "
                    f"generating new call_id: {call_id}"
                )

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
) -> tuple[list[Content] | None, list[ToolCall]]:
    """Extract assistant content and function calls from model parts.

    Returns content as a list of Content parts (never simplified to string)
    to maintain consistency with model output format for message ID stability.

    Also extracts thoughtSignature from function call parts and stores them
    in ContentReasoning blocks (following the pattern from main Google provider).
    Per Gemini API docs, only the first function call in a message has a signature.

    Additionally looks for embedded <think> tags in text parts to restore
    reasoning content (including summaries) that was preserved through the CLI.
    """
    content_parts: list[Content] = []
    tool_calls: list[ToolCall] = []
    first_fc_signature_captured = False

    # First pass: look for embedded <think> tags in text parts
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
            # Skip text parts that are embedded <think> tags (internal use only)
            _, capsule = parse_content_with_reasoning(text)
            if capsule is not None:
                continue
            # Also skip "(no content)" placeholder that CLI adds
            if text == "(no content)":
                continue
            content_parts.append(ContentText(text=text))

        elif "functionCall" in part or "function_call" in part:
            # Function call -> ToolCall
            func_call = part.get("functionCall", part.get("function_call", {}))
            func_name = func_call.get("name", "")
            args = func_call.get("args", {})

            # Capture thought_signature on first function call (per Gemini API docs)
            # Store it as a ContentReasoning block with redacted=True
            # This follows the pattern from the main Google provider.
            thought_sig = part.get("thoughtSignature", part.get("thought_signature"))

            # If no direct signature on part, check embedded <think> tag
            if not thought_sig and not first_fc_signature_captured:
                if embedded_capsule:
                    thought_sig = embedded_capsule.reasoning

            if thought_sig and not first_fc_signature_captured:
                # JSON API returns signature as base64 string already
                if isinstance(thought_sig, str):
                    sig_str = thought_sig
                else:
                    # If bytes (unlikely in JSON), base64 encode it
                    sig_str = base64.b64encode(thought_sig).decode()

                # Use full capsule if available (preserves summary)
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

            # Ensure args is a dict
            if not isinstance(args, dict):
                args = {"value": args}

            # Generate a DETERMINISTIC call ID based on function name, args, and position
            # This ensures the same call always gets the same ID for message ID stability
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

    # Keep content as list to match model output format for ID stability
    # (Don't simplify to string even if only one text part)
    if content_parts:
        return content_parts, tool_calls
    else:
        return None, tool_calls


def gemini_response_from_output(output: ModelOutput, model_name: str) -> dict[str, Any]:
    """Translate Inspect ModelOutput to Google Gemini API response format.

    Also handles thought_signature by looking for ContentReasoning blocks with
    redacted=True and attaching the signature to the first function call.

    Additionally embeds the signature in a text part with a special marker so that
    the CLI will preserve it in its history reconstruction. We then extract it
    in messages_from_google_contents when receiving the next request.
    """
    parts: list[dict[str, Any]] = []
    working_reasoning_block: ContentReasoning | None = None

    # Add text content and capture reasoning blocks
    if output.message.content:
        if isinstance(output.message.content, str):
            if output.message.content:
                parts.append({"text": output.message.content})
        else:
            for c in output.message.content:
                if isinstance(c, ContentText):
                    if c.text:
                        parts.append({"text": c.text})
                elif isinstance(c, ContentReasoning):
                    # Store reasoning block with signature for attaching to first tool call
                    if c.redacted and c.reasoning:
                        working_reasoning_block = c

    # Add function calls with signature as sibling property (per Gemini API docs)
    # thoughtSignature is a sibling to functionCall, not a separate part
    if output.message.tool_calls:
        for idx, tc in enumerate(output.message.tool_calls):
            # Parse arguments back to dict
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

            # Attach signature to first function call only (per Gemini API docs)
            if idx == 0 and working_reasoning_block is not None:
                fc_part["thoughtSignature"] = working_reasoning_block.reasoning

            parts.append(fc_part)

    # If we have a reasoning block, embed it as a <think> tag text part.
    # This preserves the full reasoning content (including summary) through
    # the CLI's history reconstruction, which strips API-level thoughtSignature
    # but preserves text parts. Uses the same serialization as the Responses path.
    if working_reasoning_block is not None:
        think_tag = reasoning_to_think_tag(working_reasoning_block)
        # Insert before function calls
        insert_pos = 0
        for i, p in enumerate(parts):
            if "functionCall" in p:
                insert_pos = i
                break
        parts.insert(insert_pos, {"text": think_tag})

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
