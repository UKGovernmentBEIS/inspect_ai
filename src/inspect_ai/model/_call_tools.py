import asyncio
import inspect
from dataclasses import is_dataclass
from textwrap import dedent
from typing import (
    Any,
    Callable,
    Dict,
    List,
    NamedTuple,
    Type,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from jsonschema import Draft7Validator
from pydantic import BaseModel

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.text import truncate_string_to_bytes
from inspect_ai.model._trace import trace_tool_mesage
from inspect_ai.tool import Tool, ToolCall, ToolError, ToolInfo
from inspect_ai.tool._tool import (
    ToolApprovalError,
    ToolParsingError,
)
from inspect_ai.tool._tool_call import ToolCallContent, ToolCallError
from inspect_ai.tool._tool_def import ToolDef, tool_defs
from inspect_ai.tool._tool_info import parse_docstring
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.util import OutputLimitExceededError

from ._chat_message import ChatMessageAssistant, ChatMessageTool
from ._generate_config import active_generate_config


async def call_tools(
    message: ChatMessageAssistant,
    tools: list[Tool] | list[ToolDef] | list[Tool | ToolDef],
    max_output: int | None = None,
) -> list[ChatMessageTool]:
    """Perform tool calls in assistant message.

    Args:
       message (ChatMessageAssistant): Assistant message
       tools (list[Tool]): Available tools
       max_output (int | None): Maximum output length (in bytes).
          Defaults to max_tool_output from active GenerateConfig
          (16 * 1024 by default).

    Returns:
       List of tool calls
    """
    if message.tool_calls:
        from inspect_ai.log._transcript import (
            ToolEvent,
            Transcript,
            init_transcript,
            track_store_changes,
            transcript,
        )

        tdefs = tool_defs(tools)

        async def call_tool_task(call: ToolCall) -> tuple[ChatMessageTool, ToolEvent]:
            # create a transript for this call
            init_transcript(Transcript(name=call.function))

            result: Any = ""
            tool_error: ToolCallError | None = None
            try:
                with track_store_changes():
                    result = await call_tool(tdefs, message.text, call)
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
                    "output_limit",
                    f"The tool output limit of {ex.limit_str} was exceeded.",
                )
                result = ex.truncated_output or ""
            except ToolParsingError as ex:
                tool_error = ToolCallError("parsing", ex.message)
            except ToolApprovalError as ex:
                tool_error = ToolCallError("approval", ex.message)
            except ToolError as ex:
                tool_error = ToolCallError("unknown", ex.message)

            # massage result, leave list[Content] alone, convert all other
            # types to string as that is what the model APIs accept
            truncated: tuple[int, int] | None = None
            if isinstance(result, list) and (
                isinstance(result[0], ContentText | ContentImage)
            ):
                content: str | list[Content] = result
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
                view=tool_call_view(call, tdefs),
                error=tool_error,
                events=transcript().events,
            )

            # return message and event
            return ChatMessageTool(
                content=content,
                tool_call_id=call.id,
                function=call.function,
                error=tool_error,
            ), event

        # call tools in parallel unless disabled by one of the tools
        if disable_parallel_tools(tdefs):
            results: list[tuple[ChatMessageTool, ToolEvent]] = []
            for call in message.tool_calls:
                task = asyncio.create_task(call_tool_task(call))
                results.append(await task)
        else:
            tasks = [call_tool_task(call) for call in message.tool_calls]
            results = await asyncio.gather(*tasks)

        # trace and fire tool events for each result
        for tool_message, event in [result for result in results]:
            trace_tool_mesage(tool_message)
            transcript()._event(event)

        # return tool messages
        return [result[0] for result in results]

    else:
        return []


async def call_tool(tools: list[ToolDef], message: str, call: ToolCall) -> Any:
    # if there was an error parsing the ToolCall, raise that
    if call.parse_error:
        raise ToolParsingError(call.parse_error)

    # find the tool
    tool_def = next((tool for tool in tools if tool.name == call.function), None)
    if tool_def is None:
        raise ToolParsingError(f"Tool {call.function} not found")

    # if we have a tool approver, apply it now
    from inspect_ai.approval._apply import apply_tool_approval

    approved, approval = await apply_tool_approval(message, call, tool_def.viewer)
    if not approved:
        raise ToolApprovalError(approval.explanation if approval else None)
    if approval and approval.modified:
        call = approval.modified

    # validate the schema of the passed object
    validation_errors = validate_tool_input(call.arguments, tool_def.parameters)
    if validation_errors:
        raise ToolParsingError(validation_errors)

    # get arguments (with creation of dataclasses, pydantic objects, etc.)
    arguments = tool_params(call.arguments, tool_def.tool)

    # call the tool
    result = await tool_def.tool(**arguments)

    # return result
    return result


def tools_info(
    tools: list[Tool]
    | list[ToolDef]
    | list[ToolInfo]
    | list[Tool | ToolDef | ToolInfo],
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
                )
            )
    return tools_info


def disable_parallel_tools(
    tools: list[Tool]
    | list[ToolDef]
    | list[ToolInfo]
    | list[Tool | ToolDef | ToolInfo],
) -> bool:
    for tool in tools:
        if isinstance(tool, Tool):
            tool = ToolDef(tool)
        if isinstance(tool, ToolDef) and not tool.parallel:
            return True
    return False


def tool_params(input: dict[str, Any], func: Callable[..., Any]) -> dict[str, Any]:
    # parse function typeinfo
    signature = inspect.signature(func)
    type_hints = get_type_hints(func)
    docstring = inspect.getdoc(func)

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
        elif param.default is not None:
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
        else:
            return input
    elif origin is list or origin is List:
        if args:
            return [tool_param(args[0], x) for x in input]
        else:
            return input
    elif origin is dict or origin is Dict:
        if args and len(args) > 1:
            return {k: tool_param(args[1], v) for k, v in input}
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
        truncated_output = dedent(f"""
            The output of your call to {tool_name} was too long to be displayed.
            Here is a truncated version:
            <START_TOOL_OUTPUT>
            {truncated.output}
            <END_TOOL_OUTPUT>""")
        return TruncatedToolOutput(
            truncated_output, truncated.original_bytes, active_max_output
        )
    else:
        return None
