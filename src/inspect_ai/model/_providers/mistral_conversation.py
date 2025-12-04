import json
from typing import Any, Callable, Literal, Sequence

from mistralai import (
    CodeInterpreterTool,
    CompletionArgs,
    ConversationResponse,
    DocumentURLChunk,
    Function,
    FunctionCallEntry,
    FunctionResultEntry,
    FunctionTool,
    ImageURL,
    ImageURLChunk,
    InputEntries,
    MessageInputEntry,
    MessageOutputContentChunks,
    MessageOutputEntry,
    Mistral,
    TextChunk,
    ThinkChunk,
    ToolExecutionEntry,
    ToolReferenceChunk,
    Tools,
    WebSearchTool,
)
from mistralai.models import (
    JSONSchema,
    ResponseFormat,
    SDKError,
)
from mistralai.types import UNSET

from inspect_ai._util.citation import Citation, UrlCitation
from inspect_ai._util.constants import NO_CONTENT
from inspect_ai._util.content import (
    Content,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.url import is_http_url
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._providers.util.util import split_system_messages
from inspect_ai.tool import ToolChoice, ToolFunction, ToolInfo
from inspect_ai.tool._tool_call import ToolCall

from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
)
from .util.hooks import HttpxHooks


async def mistral_conversation_generate(
    client: Mistral,
    http_hooks: HttpxHooks,
    model: str,
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
    handle_bad_request: Callable[[SDKError], ModelOutput | Exception],
) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
    # build request
    request_id = http_hooks.start_request()
    instructions, inputs = await mistral_conversation_inputs(input, config)
    completion_args = mistral_conversation_completion_args(
        config, tool_choice if len(tools) > 0 else None
    )
    request: dict[str, Any] = dict(
        model=model,
        instructions=instructions or UNSET,
        inputs=inputs,
        tools=mistral_conversation_tools(tools) if len(tools) > 0 else UNSET,
        completion_args=completion_args,
        store=False,
        http_headers={HttpxHooks.REQUEST_ID_HEADER: request_id},
    )

    # prepare response for inclusion in model call
    response: dict[str, Any] = {}

    def model_call() -> ModelCall:
        return ModelCall.create(
            request=request,
            response=response,
            time=http_hooks.end_request(request_id),
        )

    # send request
    try:
        conv_response = await client.beta.conversations.start_async(**request)
        response = conv_response.model_dump()
    except SDKError as ex:
        if ex.status_code == 400:
            return handle_bad_request(ex), model_call()
        else:
            raise ex

    # return model output (w/ tool calls if they exist)
    choices = completion_choices_from_conversation_response(model, conv_response, tools)
    return ModelOutput(
        model=model,
        choices=choices,
        usage=ModelUsage(
            input_tokens=conv_response.usage.prompt_tokens or 0,
            output_tokens=(
                conv_response.usage.completion_tokens
                if conv_response.usage.completion_tokens is not None
                else (conv_response.usage.total_tokens or 0)
                - (conv_response.usage.prompt_tokens or 0)
            ),
            total_tokens=conv_response.usage.total_tokens or 0,
        ),
    ), model_call()


def mistral_conversation_completion_args(
    config: GenerateConfig, tool_choice: ToolChoice | None
) -> CompletionArgs:
    completion_args = CompletionArgs()
    if config.stop_seqs is not None:
        completion_args.stop = config.stop_seqs
    if config.presence_penalty is not None:
        completion_args.presence_penalty = config.presence_penalty
    if config.frequency_penalty is not None:
        completion_args.frequency_penalty = config.frequency_penalty
    if config.temperature is not None:
        completion_args.temperature = config.temperature
    if config.top_p is not None:
        completion_args.top_p = config.top_p
    if config.max_tokens is not None:
        completion_args.max_tokens = config.max_tokens
    if config.seed is not None:
        completion_args.random_seed = config.seed
    if config.response_schema is not None:
        completion_args.response_format = ResponseFormat(
            type="json_schema",
            json_schema=JSONSchema(
                name=config.response_schema.name,
                description=config.response_schema.description,
                schema_definition=config.response_schema.json_schema.model_dump(
                    exclude_none=True
                ),
                strict=config.response_schema.strict,
            ),
        )
    if tool_choice is not None:
        if isinstance(tool_choice, ToolFunction):
            # conversation API doesn't seem to have a way to pick a single tool
            tool_choice = "any"

        if tool_choice == "any":
            completion_args.tool_choice = "required"
        else:
            completion_args.tool_choice = tool_choice

    return completion_args


def mistral_conversation_tools(tools: list[ToolInfo]) -> list[Tools]:
    conversation_tools: list[Tools] = []
    for tool in tools:
        if is_internal_web_search_tool(tool):
            conversation_tools.append(WebSearchTool(type="web_search"))
        elif is_internal_code_execution_tool(tool):
            conversation_tools.append(CodeInterpreterTool(type="code_interpreter"))
        else:
            conversation_tools.append(
                FunctionTool(
                    type="function",
                    function=Function(
                        name=tool.name,
                        description=tool.description,
                        parameters=tool.parameters.model_dump(
                            exclude={"additionalProperties"}, exclude_none=True
                        ),
                    ),
                )
            )
    return conversation_tools


def is_internal_web_search_tool(tool: ToolInfo) -> bool:
    return (
        tool.name == "web_search"
        and tool.options is not None
        and "mistral" in tool.options.keys()
    )


def is_internal_code_execution_tool(tool: ToolInfo) -> bool:
    return (
        tool.name == "code_execution"
        and tool.options is not None
        and "mistral" in tool.options.get("providers", {})
    )


async def mistral_conversation_inputs(
    messages: list[ChatMessage], config: GenerateConfig
) -> tuple[str | None, list[InputEntries]]:
    # cleave out system messages
    system_messages, other_messages = split_system_messages(messages)

    # create instructions based on config and system messages
    if config.system_message is not None or len(system_messages) > 0:
        message_text: list[str] = []
        if config.system_message is not None:
            message_text.append(config.system_message)
        message_text.extend(m.text for m in system_messages)
        instructions: str | None = "\n\n".join(message_text)
    else:
        instructions = None

    # now build inputs
    inputs: list[InputEntries] = []
    pending_content: list[MessageOutputContentChunks] = []

    async def flush_pending_content() -> None:
        nonlocal pending_content
        if len(pending_content) > 0:
            inputs.append(MessageOutputEntry(content=pending_content))
            pending_content.clear()

    for message in other_messages:
        if isinstance(message, ChatMessageUser):
            inputs.append(
                MessageInputEntry(
                    role="user",
                    content=[await mistral_content_chunk(c) for c in message.content]
                    if isinstance(message.content, list)
                    else [TextChunk(text=message.content)],
                )
            )
        elif isinstance(message, ChatMessageTool):
            inputs.append(
                FunctionResultEntry(
                    tool_call_id=message.tool_call_id or str(message.function),
                    result=message.text,
                )
            )
        elif isinstance(message, ChatMessageAssistant):
            if isinstance(message.content, str):
                inputs.append(MessageOutputEntry(content=message.content))
            else:
                await flush_pending_content()
                for c in message.content:
                    if isinstance(c, ContentText | ContentImage | ContentReasoning):
                        pending_content.append(await mistral_content_chunk(c))
                        # citations (currently mistral rejects these as input)
                        # if isinstance(c, ContentText) and c.citations:
                        #     for cite in c.citations:
                        #         if isinstance(cite, UrlCitation):
                        #             pending_content.append(
                        #                 ToolReferenceChunk(
                        #                     tool="web_search",
                        #                     title=cite.title or cite.url,
                        #                     url=cite.url,
                        #                     description=cite.cited_text
                        #                     if isinstance(cite.cited_text, str)
                        #                     else UNSET,
                        #                 )
                        #             )
                    else:
                        await flush_pending_content()
                        if isinstance(c, ContentToolUse):
                            name: Literal["web_search", "code_interpreter"] | None = (
                                "web_search"
                                if c.tool_type == "web_search"
                                else "code_interpreter"
                                if c.tool_type == "code_execution"
                                else None
                            )
                            if name is None:
                                raise RuntimeError(
                                    f"Unsupported tool use for mistral: {c.tool_type}"
                                )
                            # mistral is having trouble accepting these inputs (some
                            # schema validation errors) so for now we append as text
                            inputs.append(
                                MessageOutputEntry(
                                    content=f"code_interpreter: \n\n{c.arguments}\n\n{c.result}"
                                )
                            )
                        else:
                            raise RuntimeError(
                                f"Unsupported content type for mistral: {type(c)}"
                            )

                await flush_pending_content()

            # tool calls
            for tool_call in message.tool_calls or []:
                inputs.append(
                    FunctionCallEntry(
                        tool_call_id=tool_call.id,
                        name=tool_call.function,
                        arguments=tool_call.arguments,
                    )
                )

    # return
    return instructions, inputs


async def mistral_content_chunk(
    content: Content,
) -> TextChunk | ImageURLChunk | DocumentURLChunk | ThinkChunk:
    if isinstance(content, ContentText):
        return TextChunk(text=content.text or NO_CONTENT)
    elif isinstance(content, ContentImage):
        # resolve image to url
        image_url = await file_as_data_uri(content.image)
        return ImageURLChunk(image_url=ImageURL(url=image_url, detail=content.detail))
    elif isinstance(content, ContentReasoning):
        return ThinkChunk(thinking=[TextChunk(text=content.reasoning)])
    elif isinstance(content, ContentDocument):
        if is_http_url(content.document):
            return DocumentURLChunk(
                document_url=content.document, document_name=content.filename
            )
        else:
            file_data_uri = await file_as_data_uri(content.document)
            return DocumentURLChunk(
                document_url=file_data_uri, document_name=content.filename
            )

    else:
        raise ValueError(
            f"Unexpected content type for mistral provider: {type(content)}"
        )


def completion_choices_from_conversation_response(
    model: str, response: ConversationResponse, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    content: list[Content] = []
    tool_calls: list[ToolCall] = []

    for output in response.outputs:
        if isinstance(output, MessageOutputEntry):
            if isinstance(output.content, str):
                content.append(ContentText(text=output.content))
            else:
                for index, c in enumerate(output.content):
                    if isinstance(c, TextChunk):
                        # lookahead for citations
                        citations: list[Citation] = []
                        lookahead = index + 1
                        while lookahead < len(output.content):
                            lookahead_content = output.content[lookahead]
                            if (
                                isinstance(lookahead_content, ToolReferenceChunk)
                                and lookahead_content.tool == "web_search"
                            ):
                                citations.append(
                                    UrlCitation(
                                        type="url",
                                        title=lookahead_content.title,
                                        url=lookahead_content.url or "",
                                        cited_text=lookahead_content.description
                                        if isinstance(
                                            lookahead_content.description, str
                                        )
                                        else None,
                                    )
                                )
                                lookahead += 1
                            else:
                                break
                        # append content
                        content.append(
                            content_from_mistral_content_chunk(
                                c, citations if len(citations) > 0 else None
                            )
                        )
                    elif isinstance(c, ToolReferenceChunk):
                        pass  # already scooped up by lookahead
                    elif isinstance(c, ImageURLChunk | ThinkChunk):
                        content.append(content_from_mistral_content_chunk(c))
                    else:
                        raise ValueError(
                            f"Unexpected content type from mistral: {type(c)}"
                        )
        elif isinstance(output, ToolExecutionEntry):
            if output.name == "web_search":
                tool_type: Literal["web_search", "code_execution"] = "web_search"
            elif output.name == "code_interpreter":
                tool_type = "code_execution"
            else:
                raise RuntimeError(f"Unsupported tool execution type: {output.name}")
            content.append(
                ContentToolUse(
                    tool_type=tool_type,
                    id=output.id or "",
                    name=output.name,
                    arguments=output.arguments,
                    result=json.dumps(output.info or ""),
                )
            )
        elif isinstance(output, FunctionCallEntry):
            tool_calls.append(
                ToolCall(
                    id=output.tool_call_id,
                    function=output.name,
                    arguments=output.arguments,
                )
                if isinstance(output.arguments, dict)
                else parse_tool_call(
                    output.tool_call_id, output.name, output.arguments, tools
                )
            )
        else:
            raise ValueError(
                f"Unsupported assistant output for mistral provider: {type(output)}"
            )

    return [
        ChatCompletionChoice(
            message=ChatMessageAssistant(
                content=content,
                source="generate",
                tool_calls=tool_calls if len(tool_calls) > 0 else None,
                model=model,
            ),
            stop_reason="stop",
        )
    ]


def content_from_mistral_content_chunk(
    chunk: TextChunk | ImageURLChunk | ThinkChunk,
    citations: Sequence[Citation] | None = None,
) -> Content:
    match chunk:
        case TextChunk():
            return ContentText(text=chunk.text, citations=citations)
        case ImageURLChunk():
            if isinstance(chunk.image_url, str):
                return ContentImage(image=chunk.image_url, detail="auto")
            else:
                return ContentImage(
                    image=chunk.image_url.url,
                    detail=chunk.image_url.detail  # type: ignore[arg-type]
                    if isinstance(chunk.image_url.detail, str)
                    else "auto",
                )
        case ThinkChunk():
            return ContentReasoning(
                reasoning="\n".join(
                    c.text for c in chunk.thinking if isinstance(c, TextChunk)
                )
            )
