import inspect
import json
import types
from copy import copy, deepcopy
from dataclasses import is_dataclass
from datetime import date, datetime, time
from enum import EnumMeta
from logging import getLogger
from textwrap import dedent
from types import UnionType
from typing import (
    Any,
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

import anyio
import yaml
from anyio.streams.memory import MemoryObjectSendStream
from jsonschema import Draft7Validator
from pydantic import BaseModel

from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentData,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.format import format_function_call
from inspect_ai._util.logger import warn_once
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai._util.text import truncate_string_to_bytes
from inspect_ai._util.trace import trace_action
from inspect_ai._util.working import sample_waiting_time
from inspect_ai.model._display import display_conversation_message
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool import Tool, ToolCall, ToolError, ToolInfo
from inspect_ai.tool._tool import (
    ToolApprovalError,
    ToolParsingError,
    ToolResult,
    ToolSource,
)
from inspect_ai.tool._tool_call import ToolCallContent, ToolCallError
from inspect_ai.tool._tool_def import ToolDef, tool_defs
from inspect_ai.tool._tool_info import parse_docstring
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.util import OutputLimitExceededError
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._limit import LimitExceededError, apply_limits
from inspect_ai.util._span import span

from ._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from ._generate_config import active_generate_config

logger = getLogger(__name__)


class ExecuteToolsResult(NamedTuple):
    """Result from executing tools in the last assistant message.

    In conventional tool calling scenarios there will be only a list
    of `ChatMessageTool` appended and no-output. However, if there
    are `handoff()` tools (used in multi-agent systems) then other
    messages may be appended and an `output` may be available as well.
    """

    messages: list[ChatMessage]
    """Messages added to conversation."""

    output: ModelOutput | None = None
    """Model output if a generation occurred within the conversation."""


async def execute_tools(
    messages: list[ChatMessage],
    tools: Sequence[Tool | ToolDef | ToolSource] | ToolSource,
    max_output: int | None = None,
) -> ExecuteToolsResult:
    """Perform tool calls in the last assistant message.

    Args:
       messages: Current message list
       tools (list[Tool]): Available tools
       max_output (int | None): Maximum output length (in bytes).
          Defaults to max_tool_output from active GenerateConfig
          (16 * 1024 by default).

    Returns:
       Messages added to the conversation and final model output (if any)
    """
    message = messages[-1]
    if isinstance(message, ChatMessageAssistant) and message.tool_calls:
        from inspect_ai.log._transcript import ToolEvent, transcript

        tdefs = await tool_defs(tools)

        async def call_tool_task(
            call: ToolCall,
            event: ToolEvent,
            conversation: list[ChatMessage],
            send_stream: MemoryObjectSendStream[
                tuple[ExecuteToolsResult, ToolEvent, Exception | None]
            ],
        ) -> None:
            result: ToolResult = ""
            messages: list[ChatMessage] = []
            output: ModelOutput | None = None
            agent: str | None = None
            tool_error: ToolCallError | None = None
            tool_exception: Exception | None = None
            try:
                try:
                    result, messages, output, agent = await call_tool(
                        tdefs, message.text, call, event, conversation
                    )
                # unwrap exception group
                except Exception as ex:
                    inner_ex = inner_exception(ex)
                    raise inner_ex.with_traceback(inner_ex.__traceback__)

            except TimeoutError:
                tool_error = ToolCallError(
                    "timeout", "Command timed out before completing."
                )
            except UnicodeDecodeError as ex:
                tool_error = ToolCallError(
                    "unicode_decode",
                    f"Error decoding bytes to {ex.encoding}: {ex.reason}",
                )
            except PermissionError as ex:
                err = f"{ex.strerror}."
                if isinstance(ex.filename, str):
                    err = f"{err} Filename '{ex.filename}'."
                tool_error = ToolCallError("permission", err)
            except FileNotFoundError as ex:
                tool_error = ToolCallError(
                    "file_not_found",
                    f"File '{ex.filename}' was not found.",
                )
            except IsADirectoryError as ex:
                err = f"{ex.strerror}."
                if isinstance(ex.filename, str):
                    err = f"{err} Filename '{ex.filename}'."
                tool_error = ToolCallError("is_a_directory", err)
            except OutputLimitExceededError as ex:
                tool_error = ToolCallError(
                    "limit",
                    f"The tool exceeded its output limit of {ex.limit_str}.",
                )
                result = ex.truncated_output or ""
            except LimitExceededError as ex:
                tool_error = ToolCallError(
                    "limit",
                    f"The tool exceeded its {ex.type} limit of {ex.limit_str}.",
                )
            except ToolParsingError as ex:
                tool_error = ToolCallError("parsing", ex.message)
            except ToolApprovalError as ex:
                tool_error = ToolCallError("approval", ex.message)
            except ToolError as ex:
                tool_error = ToolCallError("unknown", ex.message)
            except Exception as ex:
                tool_exception = ex

            # massage result, leave list[Content] alone, convert all other
            # types to string as that is what the model APIs accept
            truncated: tuple[int, int] | None = None
            if isinstance(
                result,
                ContentText | ContentImage | ContentAudio | ContentVideo | ContentData,
            ):
                content: str | list[Content] = [result]
            elif isinstance(result, list) and (
                len(result) == 0
                or isinstance(
                    result[0],
                    ContentText
                    | ContentImage
                    | ContentAudio
                    | ContentVideo
                    | ContentData,
                )
            ):
                content = result
            else:
                content = str(result)

                # truncate if necessary
                truncated_output = truncate_tool_output(
                    call.function, content, max_output
                )
                if truncated_output:
                    content = truncated_output.output
                    truncated = (
                        truncated_output.raw_bytes,
                        truncated_output.truncated_bytes,
                    )

            # create event
            event = ToolEvent(
                id=call.id,
                function=call.function,
                arguments=call.arguments,
                result=content,
                truncated=truncated,
                view=call.view,
                error=tool_error,
                agent=agent,
            )

            # yield message and event
            async with send_stream:
                await send_stream.send(
                    (
                        ExecuteToolsResult(
                            messages=[
                                ChatMessageTool(
                                    content=content,
                                    tool_call_id=call.id,
                                    function=call.function,
                                    error=tool_error,
                                    internal=call.internal,
                                )
                            ]
                            + messages,
                            output=output,
                        ),
                        event,
                        tool_exception,
                    )
                )

        # call tools
        result_messages: list[ChatMessage] = []
        result_output: ModelOutput | None = None
        for call in message.tool_calls:
            # create pending tool event and add it to the transcript
            # (record the waiting time for the sample so we can compare
            # it at the end to deduce total waiting time inside the tool
            # call (in turn used to calculate working time)
            waiting_time_start = sample_waiting_time()
            event = ToolEvent(
                id=call.id,
                function=call.function,
                arguments=call.arguments,
                view=call.view,
                internal=call.internal,
                pending=True,
            )

            # execute the tool call. if the operator cancels the
            # tool call then synthesize the appropriate message/event
            send_stream, receive_stream = anyio.create_memory_object_stream[
                tuple[ExecuteToolsResult, ToolEvent, Exception | None]
            ]()

            result_exception = None
            async with anyio.create_task_group() as tg:
                tg.start_soon(call_tool_task, call, event, messages, send_stream)
                event._set_cancel_fn(tg.cancel_scope.cancel)
                async with receive_stream:
                    (
                        result,
                        result_event,
                        result_exception,
                    ) = await receive_stream.receive()

            if event.cancelled:
                tool_message = ChatMessageTool(
                    content="",
                    function=call.function,
                    tool_call_id=call.id,
                    error=ToolCallError(
                        "timeout", "Command timed out before completing."
                    ),
                )
                result_event = ToolEvent(
                    id=call.id,
                    function=call.function,
                    arguments=call.arguments,
                    result=tool_message.content,
                    truncated=None,
                    view=call.view,
                    error=tool_message.error,
                )
                transcript().info(
                    f"Tool call '{call.function}' was cancelled by operator."
                )
                result_messages.append(tool_message)
                display_conversation_message(tool_message)
            elif result is not None:
                for message in result.messages:
                    result_messages.append(message)
                    display_conversation_message(message)
                if result.output is not None:
                    result_output = result.output

            # update the event with the results
            waiting_time_end = sample_waiting_time()
            event._set_result(
                result=result_event.result,
                truncated=result_event.truncated,
                error=result_event.error,
                waiting_time=waiting_time_end - waiting_time_start,
                agent=result_event.agent,
                failed=True if result_exception else None,
            )
            transcript()._event_updated(event)

            # if there was an exception then re-raise it -- we do this
            # after updating the event so that we flush the transcript
            # for the event
            if result_exception is not None:
                raise result_exception

        # return tool messages
        return ExecuteToolsResult(result_messages, result_output)

    else:
        return ExecuteToolsResult([])


async def call_tool(
    tools: list[ToolDef],
    message: str,
    call: ToolCall,
    event: BaseModel,
    conversation: list[ChatMessage],
) -> tuple[ToolResult, list[ChatMessage], ModelOutput | None, str | None]:
    from inspect_ai.agent._handoff import AgentTool
    from inspect_ai.log._transcript import SampleLimitEvent, ToolEvent, transcript

    # dodge circular import
    assert isinstance(event, ToolEvent)

    # this function is responsible for transcript events so that it can
    # put them in the right enclosure (e.g. handoff/agent/tool). This
    # means that if we throw early we need to do the enclosure when raising.
    async def record_tool_parsing_error(error: str) -> Exception:
        async with span(name=call.function, type="tool"):
            transcript()._event(event)
        return ToolParsingError(error)

    # if there was an error parsing the ToolCall, raise that
    if call.parse_error:
        raise await record_tool_parsing_error(call.parse_error)

    # find the tool
    tool_def = next((tool for tool in tools if tool.name == call.function), None)
    if tool_def is None:
        raise await record_tool_parsing_error(f"Tool {call.function} not found")

    # if we have a tool approver, apply it now
    from inspect_ai.approval._apply import apply_tool_approval

    approved, approval = await apply_tool_approval(
        message, call, tool_def.viewer, conversation
    )
    if not approved:
        if approval and approval.decision == "terminate":
            message = "Tool call approver requested termination."
            transcript()._event(
                SampleLimitEvent(type="operator", limit=1, message=message)
            )
            raise TerminateSampleError(message)
        else:
            raise ToolApprovalError(approval.explanation if approval else None)
    if approval and approval.modified:
        call = approval.modified

    # validate the schema of the passed object
    validation_errors = validate_tool_input(call.arguments, tool_def.parameters)
    if validation_errors:
        raise await record_tool_parsing_error(validation_errors)

    # get arguments (with creation of dataclasses, pydantic objects, etc.)
    arguments = tool_params(call.arguments, tool_def.tool)

    # call the tool
    with trace_action(
        logger, "Tool Call", format_function_call(tool_def.name, arguments, width=1000)
    ):
        if isinstance(tool_def.tool, AgentTool):
            async with span(tool_def.tool.name, type="handoff"):
                async with span(name=call.function, type="tool"):
                    transcript()._event(event)
                    return await agent_handoff(tool_def, call, conversation)

        # normal tool call
        else:
            async with span(name=call.function, type="tool"):
                transcript()._event(event)
                result: ToolResult = await tool_def.tool(**arguments)
                return result, [], None, None


async def agent_handoff(
    tool_def: ToolDef, call: ToolCall, conversation: list[ChatMessage]
) -> tuple[ToolResult, list[ChatMessage], ModelOutput | None, str]:
    from inspect_ai.agent._agent import AgentState
    from inspect_ai.agent._handoff import AgentTool

    # alias agent tool and get agent name
    agent_tool = cast(AgentTool, tool_def.tool)
    agent_name = registry_unqualified_name(agent_tool.agent)

    # copy list
    agent_conversation = copy(conversation)

    # remove other tool calls from the assistant message so the
    # conversation remains valid (the model may have called multiple
    # tools in parallel and we won't be handling the other calls)
    last_message = agent_conversation[-1]
    if isinstance(last_message, ChatMessageAssistant) and last_message.tool_calls:
        agent_conversation[-1] = agent_conversation[-1].model_copy(
            update=dict(
                tool_calls=[
                    tool_call
                    for tool_call in last_message.tool_calls
                    if tool_call.id == call.id
                ]
            )
        )

    # ammend the conversation with a ChatMessageTool to indicate
    # to the downstream agent that we satisfied the call
    tool_result = f"Successfully transferred to {agent_name}."
    agent_conversation.append(
        ChatMessageTool(
            content=tool_result,
            tool_call_id=call.id,
            function=call.function,
            internal=call.internal,
        )
    )

    # run input filter if we have one
    if agent_tool.input_filter is not None:
        agent_conversation = await agent_tool.input_filter(agent_conversation)

    # remove system messages (as they can refer to tools or other special
    # instructions that don't apply to the sub-agent)
    agent_conversation = [
        m for m in agent_conversation if not isinstance(m, ChatMessageSystem)
    ]

    # inject curried args
    arguments = {**call.arguments, **agent_tool.kwargs}

    # parse arguments
    arguments = tool_params(arguments, agent_tool.agent)
    del arguments["state"]

    # run the agent with limits
    limit_error: LimitExceededError | None = None
    agent_state = AgentState(messages=copy(agent_conversation))
    try:
        # The agent_tool's limits will be applied multiple times if the agent is handed
        # off to multiple times which is not supported, so create a copy of each limit.
        with apply_limits(deepcopy(agent_tool.limits)):
            async with span(name=agent_name, type="agent"):
                agent_state = await agent_tool.agent(agent_state, **arguments)
    except LimitExceededError as ex:
        limit_error = ex

    # determine which messages are new and return only those (but exclude new
    # system messages as they an internal matter for the handed off to agent.
    # also, inject the agent's name as a prefix in assistant messages
    conversation_message_ids = [message.id for message in agent_conversation]
    agent_messages: list[ChatMessage] = []
    for m in agent_state.messages:
        if m.id not in conversation_message_ids:
            if isinstance(m, ChatMessageAssistant):
                m = prepend_agent_name(m, agent_name)
            if not isinstance(m, ChatMessageSystem):
                agent_messages.append(m)

    # run output filter if we have one
    if agent_tool.output_filter is not None:
        agent_messages = await agent_tool.output_filter(agent_messages)

    if limit_error is not None:
        agent_messages.append(
            ChatMessageUser(
                content=(
                    f"The {agent_name} exceeded its {limit_error.type} limit of "
                    f"{limit_error.limit_str}."
                )
            )
        )
    # if we end with an assistant message then add a user message
    # so that the calling agent carries on
    elif len(agent_messages) == 0 or isinstance(
        agent_messages[-1], ChatMessageAssistant
    ):
        agent_messages.append(
            ChatMessageUser(content=f"The {agent_name} agent has completed its work.")
        )

    return (tool_result, agent_messages, agent_state.output, agent_name)


def prepend_agent_name(
    message: ChatMessageAssistant, agent_name: str
) -> ChatMessageAssistant:
    if isinstance(message.content, str):
        return message.model_copy(
            update=dict(content=f"[{agent_name}] {message.content}")
        )
    else:
        content = copy(message.content)
        for i in range(0, len(content)):
            if isinstance(content[i], ContentText):
                text = cast(ContentText, content[i]).text
                if text:
                    content[i] = content[i].model_copy(
                        update=dict(text=f"[{agent_name}] {text}")
                    )
                break
        return message.model_copy(update=dict(content=content))


def tools_info(
    tools: Sequence[Tool | ToolDef | ToolInfo],
) -> list[ToolInfo]:
    tools_info: list[ToolInfo] = []
    for tool in tools:
        if isinstance(tool, ToolInfo):
            tools_info.append(tool)
        else:
            if isinstance(tool, Tool):
                tool = ToolDef(tool)
            tools_info.append(
                ToolInfo(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                    options=tool.options,
                )
            )
    return tools_info


def disable_parallel_tools(
    tools: Sequence[Tool | ToolDef | ToolInfo | ToolSource] | ToolSource,
) -> bool:
    if not isinstance(tools, ToolSource):
        for tool in tools:
            if isinstance(tool, Tool):
                tool = ToolDef(tool)
            if isinstance(tool, ToolDef) and not tool.parallel:
                return True
    return False


def type_hint_includes_none(type_hint: Type[Any] | None) -> bool:
    origin = get_origin(type_hint)

    if origin in {Union, UnionType}:
        return type(None) in get_args(type_hint)
    elif origin is Optional:
        return True
    return False


def tool_params(input: dict[str, Any], func: Callable[..., Any]) -> dict[str, Any]:
    # parse function typeinfo
    signature = inspect.signature(func)
    type_hints = get_type_hints(func)
    docstring = inspect.getdoc(func)

    # if the function takes **kwargs: Any then just pass the tool arguments through
    if "kwargs" in type_hints and type_hints["kwargs"] == Any:
        return input

    # build params
    params: dict[str, Any] = {}
    for param_name, param in signature.parameters.items():
        # Parse docstring
        docstring_info = parse_docstring(docstring, param_name)

        # get type hint (fallback to docstring as required)
        type_hint: Type[Any] | None = None
        if param_name in type_hints:
            type_hint = type_hints[param_name]
        # as a fallback try to parse it from the docstring
        elif "docstring_type" in docstring_info:
            docstring_type = docstring_info["docstring_type"]
            type_hint = getattr(__builtins__, docstring_type, None)

        # error if there is no type_hint
        if type_hint is None:
            raise ValueError(f"No type annotation available for parameter {param_name}")

        # yield parameter (fail if not passed and there is no default)
        if param_name in input:
            params[param_name] = tool_param(type_hint, input.get(param_name))
        elif param.default is not None or type_hint_includes_none(type_hint):
            params[param_name] = param.default
        else:
            raise ToolParsingError(
                f"Required parameter {param_name} not provided to tool call."
            )

    return params


def tool_param(type_hint: Type[Any], input: Any) -> Any:
    origin = get_origin(type_hint)
    args = get_args(type_hint)

    if origin is None:
        if type_hint in [int, str, float, bool]:
            try:
                return type_hint(input)
            except (ValueError, TypeError):
                raise ToolParsingError(
                    f"Unable to convert '{input}' to {type_hint.__name__}"
                )
        elif type_hint == datetime:
            if input.endswith("Z"):
                # convert trailing Z to +00:00
                input = input[:-1] + "+00:00"
            return datetime.fromisoformat(input)
        elif type_hint == date:
            return date.fromisoformat(input)
        elif type_hint == time:
            return time.fromisoformat(input)
        elif is_typeddict(type_hint):
            typeddict_data: dict[str, Any] = {}
            annotations = get_type_hints(type_hint)
            for name, hint in annotations.items():
                typeddict_data[name] = tool_param(hint, input.get(name))
            return typeddict_data
        elif is_dataclass(type_hint):
            dataclass_data: dict[str, Any] = {}
            fields = type_hint.__dataclass_fields__  # type: ignore
            for name, field in fields.items():
                dataclass_data[name] = tool_param(field.type, input.get(name))  # type: ignore
            return type_hint(**dataclass_data)
        elif issubclass(type_hint, BaseModel):
            return type_hint(**input)
        elif isinstance(type_hint, EnumMeta):
            return type_hint(input)
        else:
            return input
    elif origin is list or origin is List:
        if args:
            return [tool_param(args[0], x) for x in input]
        else:
            return input
    elif origin is set or origin is Set:
        if args:
            return {tool_param(args[0], x) for x in input}
        else:
            return set(input)
    elif origin is tuple or origin is Tuple:
        if args:
            return tuple([tool_param(args[0], x) for x in input])
        else:
            return tuple(input)
    elif origin is dict or origin is Dict:
        if args and len(args) > 1:
            return {k: tool_param(args[1], v) for k, v in input.items()}
        else:
            return input
    elif origin is Union or origin is types.UnionType:
        if args[1] is type(None) and input is not None:
            return tool_param(args[0], input)
        else:
            return input
    else:
        return input


def tool_call_view(call: ToolCall, tdefs: list[ToolDef]) -> ToolCallContent | None:
    tool_def = next((tool for tool in tdefs if tool.name == call.function), None)
    if tool_def and tool_def.viewer:
        return tool_def.viewer(call).call
    else:
        return None


def validate_tool_input(input: dict[str, Any], parameters: ToolParams) -> str | None:
    schema = parameters.model_dump(exclude_none=True)
    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors(input))
    if errors:
        message = "\n".join(
            [f"Found {len(errors)} validation errors parsing tool input arguments:"]
            + [f"- {error.message}" for error in errors]
        )
        return message
    else:
        return None


class TruncatedToolOutput(NamedTuple):
    output: str
    raw_bytes: int
    truncated_bytes: int


def truncate_tool_output(
    tool_name: str, output: str, max_output: int | None
) -> TruncatedToolOutput | None:
    # determine active max output
    active_max_output = max_output
    if active_max_output is None:
        active_max_output = active_generate_config().max_tool_output
        if active_max_output is None:
            active_max_output = 16 * 1024

    # truncate if required
    truncated = truncate_string_to_bytes(output, active_max_output)
    if truncated:
        truncated_output = dedent("""
            The output of your call to {tool_name} was too long to be displayed.
            Here is a truncated version:
            <START_TOOL_OUTPUT>
            {truncated_output}
            <END_TOOL_OUTPUT>
            """).format(tool_name=tool_name, truncated_output=truncated.output)
        return TruncatedToolOutput(
            truncated_output, truncated.original_bytes, active_max_output
        )
    else:
        return None


def tool_parse_error_message(arguments: str, ex: Exception) -> str:
    return f"Error parsing the following tool call arguments:\n\n{arguments}\n\nError details: {ex}"


def parse_tool_call(
    id: str, function: str, arguments: str, tools: list[ToolInfo] | None = None
) -> ToolCall:
    """Parse a tool call from a JSON payload.

    Note that this function doesn't know about internal tool names so the caller
    should ammend the returned `ToolCall` by mapping the parsed `function` field from
    from an internal name to an inspect tool name and fixing up the `ToolCall` object
    as required to reflect this change.
    """
    error: str | None = None
    arguments_dict: dict[str, Any] = {}

    def report_parse_error(ex: Exception) -> None:
        nonlocal error
        error = tool_parse_error_message(arguments, ex)
        logger.info(error)

    # if the arguments is a dict, then handle it with a plain json.loads
    arguments = arguments.strip()
    if arguments.startswith("{"):
        try:
            arguments_dict = json.loads(arguments)
        except json.JSONDecodeError as ex:
            report_parse_error(ex)

    # otherwise parse it as yaml (which will pickup unquoted strings, numbers, and true/false)
    # and then create a dict that maps it to the first function argument
    elif function and tools:
        tool_info = next(
            (
                tool
                for tool in tools
                if tool.name == function and len(tool.parameters.properties) > 0
            ),
            None,
        )
        if tool_info:
            param_names = list(tool_info.parameters.properties.keys())
            try:
                value = yaml.safe_load(arguments)
                arguments_dict[param_names[0]] = value
            except yaml.error.YAMLError:
                # If the yaml parser fails, we treat it as a string argument.
                arguments_dict[param_names[0]] = arguments

    # return ToolCall with error payload
    return ToolCall(
        id=id,
        function=function,
        arguments=arguments_dict,
        parse_error=error,
    )


async def call_tools(
    message: ChatMessageAssistant,
    tools: list[Tool] | list[ToolDef] | list[Tool | ToolDef],
    max_output: int | None = None,
) -> list[ChatMessageTool]:
    """Perform tool calls in assistant message.

    This method is deprecated. Use the `execute_tools()` method instead
    (which correctly handles agent `handoff()` tools).

    Args:
       message: Assistant message.
       tools (list[Tool]): Available tools
       max_output (int | None): Maximum output length (in bytes).
          Defaults to max_tool_output from active GenerateConfig
          (16 * 1024 by default).

    Returns:
       Messages added to the conversation.
    """
    warn_once(
        logger,
        "call_tools is deprecated -- please use execute_tools instead (as it supports agent handoff tools)",
    )

    messages, _ = await execute_tools([message], tools, max_output)
    return [m for m in messages if isinstance(m, ChatMessageTool)]
