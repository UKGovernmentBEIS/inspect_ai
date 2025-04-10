import inspect
from typing import (
    Any,
    Callable,
    Dict,
    get_args,
    get_type_hints,
)

from docstring_parser import Docstring, parse
from pydantic import BaseModel, Field

from inspect_ai.util._json import JSONType, json_schema

from ._tool_description import tool_description
from ._tool_params import ToolParam, ToolParams


class ToolInfo(BaseModel):
    """Specification of a tool (JSON Schema compatible)

    If you are implementing a ModelAPI, most LLM libraries can
    be passed this object (dumped to a dict) directly as a function
    specification. For example, in the OpenAI provider:

    ```python
    ChatCompletionToolParam(
        type="function",
        function=tool.model_dump(exclude_none=True),
    )
    ```

    In some cases the field names don't match up exactly. In that case
    call `model_dump()` on the `parameters` field. For example, in the
    Anthropic provider:

    ```python
    ToolParam(
        name=tool.name,
        description=tool.description,
        input_schema=tool.parameters.model_dump(exclude_none=True),
    )
    ```
    """

    name: str
    """Name of tool."""
    description: str
    """Short description of tool."""
    parameters: ToolParams = Field(default_factory=ToolParams)
    """JSON Schema of tool parameters object."""


def parse_tool_info(func: Callable[..., Any]) -> ToolInfo:
    # tool may already have registry attributes w/ tool info
    description = tool_description(func)
    if (
        description.name
        and description.description
        and description.parameters is not None
    ):
        return ToolInfo(
            name=description.name,
            description=description.description,
            parameters=description.parameters,
        )

    signature = inspect.signature(func)
    type_hints = get_type_hints(func)
    docstring = inspect.getdoc(func)
    parsed_docstring: Docstring | None = parse(docstring) if docstring else None

    info = ToolInfo(name=func.__name__, description="")

    for param_name, param in signature.parameters.items():
        tool_param = ToolParam()

        # Parse docstring
        docstring_info = parse_docstring(docstring, param_name)

        # Get type information from type annotations
        if param_name in type_hints:
            tool_param = json_schema(type_hints[param_name])
        # as a fallback try to parse it from the docstring
        # (this is minimally necessary for backwards compatiblity
        #  with tools gen1 type parsing, which only used docstrings)
        elif "docstring_type" in docstring_info:
            json_type = python_type_to_json_type(docstring_info["docstring_type"])
            if json_type and (json_type in get_args(JSONType)):
                tool_param = ToolParam(type=json_type)

        # Get default value
        if param.default is param.empty:
            info.parameters.required.append(param_name)
        else:
            tool_param.default = param.default

        # Add description from docstring
        if "description" in docstring_info:
            tool_param.description = docstring_info["description"]

        # append the tool param
        info.parameters.properties[param_name] = tool_param

    # Add function description if available
    if parsed_docstring:
        if parsed_docstring.description:
            info.description = parsed_docstring.description.strip()
        elif parsed_docstring.long_description:
            info.description = parsed_docstring.long_description.strip()
        elif parsed_docstring.short_description:
            info.description = parsed_docstring.short_description.strip()

        # Add examples if available
        if parsed_docstring.examples:
            examples = "\n\n".join(
                [(example.description or "") for example in parsed_docstring.examples]
            )
            info.description = f"{info.description}\n\nExamples\n\n{examples}"

    return info


def parse_docstring(docstring: str | None, param_name: str) -> Dict[str, str]:
    if not docstring:
        return {}

    parsed_docstring: Docstring = parse(docstring)

    for param in parsed_docstring.params:
        if param.arg_name == param_name:
            schema: Dict[str, str] = {"description": param.description or ""}

            if param.type_name:
                schema["docstring_type"] = param.type_name

            return schema

    return {}


def python_type_to_json_type(python_type: str) -> JSONType | None:
    match python_type:
        case "str":
            return "string"
        case "int":
            return "integer"
        case "float":
            return "number"
        case "bool":
            return "boolean"
        case "list":
            return "array"
        case "dict":
            return "object"
        case "None":
            return "null"
        case _:
            return None
