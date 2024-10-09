import asyncio
import inspect
from dataclasses import dataclass, is_dataclass
from textwrap import dedent
from typing import (
    Any,
    Callable,
    Dict,
    List,
    NamedTuple,
    Type,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from jsonschema import Draft7Validator
from pydantic import BaseModel

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.registry import registry_info
from inspect_ai._util.text import truncate_string_to_bytes
from inspect_ai.model._trace import trace_tool_mesage
from inspect_ai.tool import Tool, ToolCall, ToolError, ToolInfo
from inspect_ai.tool._tool import (
    TOOL_PARALLEL,
    TOOL_PROMPT,
    TOOL_VIEWER,
    ToolApprovalError,
    ToolParsingError,
)
from inspect_ai.tool._tool_call import ToolCallError, ToolCallViewer
from inspect_ai.tool._tool_info import (
    ToolParams,
    parse_docstring,
    parse_tool_info,
)
from inspect_ai.tool._tool_with import tool_description

from ._chat_message import ChatMessageAssistant, ChatMessageTool
from ._generate_config import active_generate_config


async def call_tools(
    message: ChatMessageAssistant,
    tools: list[Tool],
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

        # call tools in parallel
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


@dataclass
class ToolDef:
    name: str
    """Tool name."""

    description: str
    """Tool description."""

    parameters: ToolParams
    """Tool parameters"""

    parallel: bool
    """Supports parallel execution."""

    viewer: ToolCallViewer | None
    """Custom viewer for tool call"""

    tool: Callable[..., Any]
    """Callable to execute tool."""


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


def tools_info(tools: list[Tool] | list[ToolInfo]) -> list[ToolInfo]:
    if len(tools) > 0:
        if isinstance(tools[0], ToolInfo):
            return cast(list[ToolInfo], tools)
        else:
            tdefs = tool_defs(cast(list[Tool], tools))
            return [
                ToolInfo(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                )
                for tool in tdefs
            ]
    else:
        return []


def disable_parallel_tools(tools: list[Tool] | list[ToolInfo]) -> bool:
    for tool in tools:
        if isinstance(tool, Tool):
            _, _, parallel, _ = tool_registry_info(tool)
            if not parallel:
                return True
    return False


def tool_defs(tools: list[Tool]) -> list[ToolDef]:
    return [tool_def(tool) for tool in tools]


def tool_def(tool: Tool) -> ToolDef:
    # get tool_info
    name, prompt, parallel, viewer = tool_registry_info(tool)
    tool_info = parse_tool_info(tool)

    # if there is a description then append any prompt to the
    # the description (note that 'prompt' has been depreacted
    # in favor of just providing a description in the doc comment.
    if tool_info.description:
        if prompt:
            tool_info.description = f"{tool_info.description}. {prompt}"

    # if there is no description and there is a prompt, then use
    # the prompt as the description
    elif prompt:
        tool_info.description = prompt

    # no description! we can't proceed without one
    else:
        raise ValueError(f"Description not provided for tool function '{name}'")

    # validate that we have types/descriptions for paramters
    for param_name, param in tool_info.parameters.properties.items():

        def raise_not_provided_error(context: str) -> None:
            raise ValueError(
                f"{context} not provided for parameter '{param_name}' of tool function '{name}'."
            )

        if param.type == "null":
            raise_not_provided_error("Type annotation")
        elif not param.description:
            raise_not_provided_error("Description")

    # see if the user has overriden any of the tool's descriptions
    desc = tool_description(tool)
    if desc.name:
        name = desc.name
    if desc.description:
        tool_info.description = desc.description
    if desc.parameters:
        for key, description in desc.parameters.items():
            if key in tool_info.parameters.properties.keys():
                tool_info.parameters.properties[key].description = description

    # build tool def
    return ToolDef(
        name=name,
        description=tool_info.description,
        parameters=tool_info.parameters,
        parallel=parallel,
        viewer=viewer,
        tool=tool,
    )


def tool_registry_info(
    tool: Tool,
) -> tuple[str, str | None, bool, ToolCallViewer | None]:
    info = registry_info(tool)
    name = info.name.split("/")[-1]
    prompt = info.metadata.get(TOOL_PROMPT, None)
    parallel = info.metadata.get(TOOL_PARALLEL, True)
    viewer = info.metadata.get(TOOL_VIEWER, None)
    return name, prompt, parallel, viewer


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
        type_hint: Type[Any] | None
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
                dataclass_data[name] = tool_param(field.type, input.get(name))
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
